"""Local app. Serves the static replay site and a small JSON API.

Cloudflare Pages serves site/ with no process behind it. This server is the
`make run` path: the same pages, plus POST /api/run to execute a scenario.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from killswitch.dataset import load_bundle
from killswitch.engine import run_named
from killswitch.paths import SITE_DIR
from killswitch.policy import load_policy
from killswitch.pricing import load_prices

_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".png": "image/png",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}


class App:
    def __init__(self, uri: str | None = None, allow_ollama: bool = False, site_dir: Path | None = None):
        self.uri = uri
        self.dataset, self.catalog = load_bundle(uri)
        self.policy = load_policy()
        self.prices = load_prices()
        self.allow_ollama = allow_ollama
        self.site_dir = (site_dir or SITE_DIR).resolve()

    def health(self) -> dict:
        from killswitch.dataset import resolve_dataset_path

        return {
            "ok": True,
            "product": "agent-cost-killswitch",
            "provider": "mock+ollama" if self.allow_ollama else "mock",
            "dataset": str(resolve_dataset_path(self.uri)),
            "price_label": self.prices.label,
            "scenarios": [s.id for s in self.dataset.scenarios],
        }

    def run(self, scenario_id: str) -> dict:
        report = run_named(
            scenario_id,
            dataset=self.dataset,
            catalog=self.catalog,
            policy=self.policy,
            prices=self.prices,
            allow_ollama=self.allow_ollama,
            uri=self.uri,
        )
        return report.model_dump(mode="json")


def _safe_file(root: Path, url_path: str) -> Path | None:
    path = url_path.split("?", 1)[0]
    if path in ("", "/"):
        path = "/index.html"
    if path.endswith("/"):
        path += "index.html"
    candidate = (root / path.lstrip("/")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: dict) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                self._json(200, app.health())
                return
            if parsed.path == "/api/scenarios":
                self._json(
                    200,
                    {
                        "scenarios": [
                            {"id": s.id, "title": s.title, "summary": s.summary}
                            for s in app.dataset.scenarios
                        ]
                    },
                )
                return
            if parsed.path == "/api/run":
                scenario = (parse_qs(parsed.query).get("scenario") or [""])[0]
                self._run(scenario)
                return
            target = _safe_file(app.site_dir, parsed.path)
            if target is None:
                self._json(404, {"error": "not found"})
                return
            self._send(200, target.read_bytes(), _TYPES.get(target.suffix.lower(), "application/octet-stream"))

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/run":
                self._json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or "0")
            if length > 1_000_000:
                self._json(413, {"error": "body too large"})
                return
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode() or "{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "body must be JSON"})
                return
            scenario = ""
            if isinstance(payload, dict):
                scenario = str(payload.get("scenario") or "")
            self._run(scenario)

        def _run(self, scenario: str) -> None:
            if not scenario:
                self._json(400, {"error": "scenario is required"})
                return
            try:
                self._json(200, app.run(scenario))
            except KeyError:
                self._json(404, {"error": f"unknown scenario {scenario}"})

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8766, uri: str | None = None, allow_ollama: bool = False) -> None:
    app = App(uri=uri, allow_ollama=allow_ollama)
    server = ThreadingHTTPServer((host, port), make_handler(app))
    mode = "mock replay, local tier via Ollama" if allow_ollama else "mock replay"
    print(f"agent-cost-killswitch  {mode}")
    print(f"dataset  {app.health()['dataset']}")
    print(f"open     http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
