import json
import os
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest
from pydantic import ValidationError

from killswitch.dataset import load_bundle, resolve_dataset_path
from killswitch.paths import DATA_DIR, SITE_DATA_DIR
from killswitch.record import record
from killswitch.serve import App, make_handler
from http.server import ThreadingHTTPServer


def test_default_bundle_is_synthetic():
    dataset, catalog = load_bundle()
    assert dataset.synthetic is True
    assert {s.id for s in dataset.scenarios} == {
        "normal",
        "runaway-loop",
        "budget-overrun",
        "provider-outage",
    }
    assert "list_tickets" in catalog.tools


def test_dataset_uri_file_and_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("HL_DATASET_URI", raising=False)
    uri = DATA_DIR.as_uri() + "/scenarios.json"
    assert resolve_dataset_path(uri) == (DATA_DIR / "scenarios.json").resolve()
    assert resolve_dataset_path(str(DATA_DIR)).is_dir()
    dataset, _ = load_bundle(str(DATA_DIR))
    assert dataset.dataset == "houghton-labs-killswitch-demo"
    monkeypatch.setenv("HL_DATASET_URI", uri)
    assert resolve_dataset_path() == (DATA_DIR / "scenarios.json").resolve()


def test_non_synthetic_dataset_is_rejected(tmp_path):
    scenarios = tmp_path / "scenarios.json"
    tools = tmp_path / "tools.json"
    tools.write_text((DATA_DIR / "tools.json").read_text())
    raw = json.loads((DATA_DIR / "scenarios.json").read_text())
    raw["synthetic"] = False
    scenarios.write_text(json.dumps(raw))
    with pytest.raises(ValidationError):
        load_bundle(str(tmp_path))


def test_record_matches_committed_site_data(tmp_path):
    """Committed replays are the engine output. Regenerating into a temp dir must match."""
    from killswitch.record import build_reports, summary_from

    written = record(site_dir=tmp_path, summary_path=tmp_path / "mirror-summary.json")
    reports = build_reports()
    summary = summary_from(reports, reports[0]["price_disclaimer"], reports[0]["price_label"])
    assert written == summary
    committed_summary = json.loads((SITE_DATA_DIR / "summary.json").read_text())
    mirror = json.loads((DATA_DIR / "summary.json").read_text())
    assert summary == committed_summary == mirror
    for report in reports:
        path = SITE_DATA_DIR / f"{report['id']}.json"
        assert path.stat().st_size < 80_000
        assert json.loads(path.read_text()) == report
        assert report["price_label"] == "example"
        assert "example" in report["price_disclaimer"].lower()
        # The giant usage dump stays out of the replay file.
        assert "synthetic query_usage row" not in path.read_text()


def test_readme_quotes_the_recorded_amounts():
    from killswitch.paths import ROOT

    readme = (ROOT / "README.md").read_text()
    summary = json.loads((SITE_DATA_DIR / "summary.json").read_text())
    for row in summary["scenarios"]:
        assert row["spent_usd"] in readme
        assert row["projected_usd"] in readme
        assert row["id"] in readme
    assert "```mermaid" in readme
    assert "https://agent-cost-killswitch.pages.dev" in readme
    assert "placeholder" in readme.lower()


def test_http_api_runs_a_scenario():
    app = App(allow_ollama=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/")
        page = conn.getresponse()
        html = page.read().decode()
        assert page.status == 200
        assert "Agent cost kill-switch" in html
        assert "example configuration" in html
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/data/index.json")
        listing = json.loads(conn.getresponse().read())
        assert listing["scenarios"][0]["id"] == "normal"
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/api/health")
        health = json.loads(conn.getresponse().read())
        assert health["ok"] is True
        assert health["provider"] == "mock"
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", "/api/run", body=json.dumps({"scenario": "normal"}))
        report = json.loads(conn.getresponse().read())
        assert report["status"] == "completed"
        assert report["id"] == "normal"
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/api/run?scenario=missing")
        missing = conn.getresponse()
        assert missing.status == 404
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/assets/../../pyproject.toml")
        escaped = conn.getresponse()
        assert escaped.status == 404
        body = escaped.read()
        assert b"pydantic" not in body
    finally:
        server.shutdown()
        server.server_close()
