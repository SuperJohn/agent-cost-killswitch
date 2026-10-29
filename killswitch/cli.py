"""Command line. `serve`, `record`, `run`, and an optional Ollama `ask`."""

import argparse
import json
import os
import sys

from killswitch import __version__
from killswitch.dataset import load_bundle
from killswitch.engine import run_named
from killswitch.models import CompletionRequest, Message
from killswitch.money import D, cost_usd, money
from killswitch.pricing import load_prices
from killswitch.providers import OllamaProvider
from killswitch.record import markdown_table, record


def _print_report(report_dict: dict) -> None:
    halt = report_dict["halt_code"] or "-"
    print(
        f"{report_dict['id']:<18} {report_dict['status']:<10} "
        f"spent {report_dict['spent_usd']}  projected {report_dict['projected_usd']}  "
        f"depth {report_dict['depth']}  tier {report_dict['final_tier']:<10} halt {halt}"
    )


def _cmd_run(args: argparse.Namespace) -> int:
    dataset, _catalog = load_bundle(args.dataset)
    ids = [s.id for s in dataset.scenarios] if args.all or not args.scenario else [args.scenario]
    for scenario_id in ids:
        report = run_named(scenario_id, uri=args.dataset, allow_ollama=args.ollama)
        if args.json:
            print(json.dumps(report.model_dump(mode="json"), indent=2))
        else:
            _print_report(report.model_dump(mode="json"))
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    summary = record(args.dataset)
    print(markdown_table(summary))
    print(f"\nwrote {len(summary['scenarios'])} scenarios to site/data and demo/data/summary.json")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from killswitch.serve import serve

    allow = args.ollama or bool(os.environ.get("HL_OLLAMA_HOST", "").strip())
    serve(args.host, args.port, uri=args.dataset, allow_ollama=allow)
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    host = os.environ.get("HL_OLLAMA_HOST", "").strip()
    if not host:
        print("HL_OLLAMA_HOST is not set. Example: HL_OLLAMA_HOST=http://127.0.0.1:11434", file=sys.stderr)
        return 2
    prices = load_prices()
    local = prices.tier("local")
    model = os.environ.get("HL_OLLAMA_MODEL", "").strip() or local.ollama_model or "llama3.2"
    provider = OllamaProvider(host, model)
    completion = provider.complete(
        CompletionRequest(
            tier="local",
            model_id=local.model_id,
            messages=[Message(role="user", content=args.prompt)],
        )
    )
    turn = cost_usd(
        completion.prompt_tokens,
        completion.completion_tokens,
        D(local.input_per_million_usd),
        D(local.output_per_million_usd),
    )
    print(completion.content)
    print(
        f"\n{model}  {completion.prompt_tokens} in / {completion.completion_tokens} out  "
        f"example USD {money(turn)}  (price table label: {prices.label})"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="killswitch", description="Agent cost and loop kill switch")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run one scenario or all of them")
    run.add_argument("scenario", nargs="?", help="scenario id")
    run.add_argument("--all", action="store_true")
    run.add_argument("--json", action="store_true")
    run.add_argument("--dataset", default=None, help="path or file:// URI, else HL_DATASET_URI")
    run.add_argument("--ollama", action="store_true", help="send the local tier to HL_OLLAMA_HOST")
    run.set_defaults(func=_cmd_run)

    rec = sub.add_parser("record", help="regenerate site/data from the synthetic scenarios")
    rec.add_argument("--dataset", default=None)
    rec.set_defaults(func=_cmd_record)

    srv = sub.add_parser("serve", help="serve the replay site and /api/run")
    srv.add_argument("--host", default=os.environ.get("HL_HOST", "127.0.0.1"))
    srv.add_argument("--port", type=int, default=int(os.environ.get("HL_PORT", "8766")))
    srv.add_argument("--dataset", default=None)
    srv.add_argument("--ollama", action="store_true")
    srv.set_defaults(func=_cmd_serve)

    ask = sub.add_parser("ask", help="one prompt to Ollama, billed with the example price table")
    ask.add_argument("prompt")
    ask.set_defaults(func=_cmd_ask)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "run" and not args.all and not args.scenario:
        parser.error("run requires a scenario id or --all")
    return args.func(args)
