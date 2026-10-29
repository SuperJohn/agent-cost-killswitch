"""Write the replay bundle the static site reads."""

import json
from pathlib import Path

from killswitch.dataset import load_bundle
from killswitch.engine import run_scenario
from killswitch.paths import DATA_DIR, RECORDED_AT, SITE_DATA_DIR
from killswitch.policy import load_policy
from killswitch.pricing import load_prices


def dump_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def build_reports(uri: str | None = None) -> list[dict]:
    dataset, catalog = load_bundle(uri)
    policy = load_policy()
    prices = load_prices()
    reports = []
    for scenario in dataset.scenarios:
        # Recorded runs always use the mock, even if HL_OLLAMA_HOST is set.
        report = run_scenario(
            scenario,
            policy,
            prices,
            catalog,
            allow_ollama=False,
            generated_at=RECORDED_AT,
        )
        reports.append(report.model_dump(mode="json"))
    return reports


def summary_from(reports: list[dict], disclaimer: str, label: str) -> dict:
    rows = []
    for report in reports:
        rows.append(
            {
                "id": report["id"],
                "title": report["title"],
                "status": report["status"],
                "halt_code": report["halt_code"],
                "depth": report["depth"],
                "final_tier": report["final_tier"],
                "spent_usd": report["spent_usd"],
                "projected_usd": report["projected_usd"],
                "prompt_tokens": report["prompt_tokens"],
                "completion_tokens": report["completion_tokens"],
                "model_calls": report["model_calls"],
                "tool_executions": report["tool_executions"],
                "overshoot": report["overshoot"],
                "what": report["summary"],
            }
        )
    return {
        "product": "agent-cost-killswitch",
        "price_label": label,
        "disclaimer": disclaimer,
        "note": (
            "Spent and projected figures use configs/prices.yaml. "
            "They are example configuration values, not invoices."
        ),
        "generated_at": RECORDED_AT,
        "scenarios": rows,
    }


def markdown_table(summary: dict) -> str:
    lines = [
        "| scenario | outcome | depth | final tier | spent (example USD) | projected (example USD) | what happened |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in summary["scenarios"]:
        outcome = row["status"] if not row["halt_code"] else f"halted · {row['halt_code']}"
        lines.append(
            f"| {row['id']} | {outcome} | {row['depth']} | {row['final_tier']} | "
            f"{row['spent_usd']} | {row['projected_usd']} | {row['what']} |"
        )
    return "\n".join(lines)


def record(uri: str | None = None, site_dir: Path | None = None, summary_path: Path | None = None) -> dict:
    reports = build_reports(uri)
    site_dir = site_dir or SITE_DATA_DIR
    label = reports[0]["price_label"]
    disclaimer = reports[0]["price_disclaimer"]
    index = {
        "product": "agent-cost-killswitch",
        "org": "Houghton Labs",
        "price_label": label,
        "price_disclaimer": disclaimer,
        "hard_budget_usd": reports[0]["hard_budget_usd"],
        "soft_budget_usd": reports[0]["soft_budget_usd"],
        "generated_at": RECORDED_AT,
        "scenarios": [
            {
                "id": report["id"],
                "title": report["title"],
                "summary": report["summary"],
                "file": f"{report['id']}.json",
                "status": report["status"],
                "halt_code": report["halt_code"],
            }
            for report in reports
        ],
    }
    dump_json(site_dir / "index.json", index)
    for report in reports:
        dump_json(site_dir / f"{report['id']}.json", report)
    summary = summary_from(reports, disclaimer, label)
    dump_json(site_dir / "summary.json", summary)
    dump_json(summary_path or (DATA_DIR / "summary.json"), summary)
    return summary
