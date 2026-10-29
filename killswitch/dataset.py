"""Load the synthetic scenario bundle. HL_DATASET_URI overrides the path."""

import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from killswitch.models import Dataset, ToolCatalog
from killswitch.paths import DATA_DIR


def resolve_dataset_path(uri: str | None = None) -> Path:
    raw = DATA_DIR / "scenarios.json" if uri is None else uri
    if uri is None:
        env = os.environ.get("HL_DATASET_URI", "").strip()
        if env:
            raw = env
    else:
        raw = uri
    if isinstance(raw, Path):
        return raw.expanduser().resolve()
    text = str(raw).strip()
    if text.startswith("file:"):
        parsed = urlparse(text)
        if parsed.netloc not in ("", "localhost"):
            raise ValueError(f"unsupported dataset URI {text}")
        text = unquote(parsed.path)
    return Path(text).expanduser().resolve()


def bundle_paths(uri: str | None = None) -> tuple[Path, Path]:
    path = resolve_dataset_path(uri)
    if path.is_dir():
        scenarios, tools = path / "scenarios.json", path / "tools.json"
    else:
        scenarios, tools = path, path.parent / "tools.json"
    if not scenarios.is_file():
        raise FileNotFoundError(f"scenario file not found: {scenarios}")
    if not tools.is_file():
        raise FileNotFoundError(f"tool catalog not found: {tools}")
    return scenarios, tools


def load_bundle(uri: str | None = None) -> tuple[Dataset, ToolCatalog]:
    scenarios_path, tools_path = bundle_paths(uri)
    dataset = Dataset.model_validate(json.loads(scenarios_path.read_text()))
    catalog = ToolCatalog.model_validate(json.loads(tools_path.read_text()))
    return dataset, catalog


def scenario_by_id(dataset: Dataset, scenario_id: str):
    for scenario in dataset.scenarios:
        if scenario.id == scenario_id:
            return scenario
    known = ", ".join(s.id for s in dataset.scenarios)
    raise KeyError(f"unknown scenario {scenario_id!r} (known: {known})")
