"""Capture the static replay site with headless Chromium.

    python scripts/screenshots.py

Serves site/ as files only, the same way Cloudflare Pages does, and writes
docs/images/*.png. Requires Playwright (`python -m playwright install chromium`).
Not part of the default test run.
"""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"

SHOTS = [
    ("normal", "normal-complete.png", "Task finished"),
    ("budget-overrun", "budget-halt.png", "not sent"),
    ("runaway-loop", "runaway-repeat.png", "was not executed"),
    ("provider-outage", "outage-local.png", "Task finished"),
]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    handler = partial(QuietHandler, directory=str(ROOT / "site"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1280}, device_scale_factor=1)
            page.on("pageerror", lambda err: print("PAGEERROR", err))
            for scenario, name, needle in SHOTS:
                page.goto(
                    f"http://127.0.0.1:{port}/?at=end&scenario={scenario}",
                    wait_until="networkidle",
                )
                page.wait_for_selector("body[data-ready='1'][data-settled='1']")
                page.evaluate("() => document.fonts.ready")
                page.wait_for_function(
                    "(id) => document.body.dataset.scenario === id && document.body.dataset.status !== 'running'",
                    arg=scenario,
                )
                banner = page.inner_text("#banner")
                if needle not in banner:
                    raise SystemExit(f"{scenario} banner missing {needle!r}: {banner}")
                if page.locator("#live").is_visible():
                    raise SystemExit("Run live should stay hidden on the static site")
                page.screenshot(path=str(OUT / name), full_page=True)
                print(name, scenario)
            # Clicking a scenario replays it and lands on the recorded outcome.
            page.goto(f"http://127.0.0.1:{port}/?at=end&scenario=normal", wait_until="networkidle")
            page.click("[data-id='budget-overrun']")
            page.wait_for_function(
                "() => document.body.dataset.scenario === 'budget-overrun' && document.body.dataset.status === 'halted' && document.body.dataset.settled === '1'",
                timeout=15000,
            )
            if "not sent" not in page.inner_text("#banner"):
                raise SystemExit("scenario click did not reach the budget halt")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
