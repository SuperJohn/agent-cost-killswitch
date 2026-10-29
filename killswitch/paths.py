"""Repository paths. Overridable only through HL_DATASET_URI for the dataset."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "configs"
DATA_DIR = ROOT / "demo" / "data"
SITE_DIR = ROOT / "site"
SITE_DATA_DIR = SITE_DIR / "data"
PRICES_PATH = CONFIG_DIR / "prices.yaml"
POLICY_PATH = CONFIG_DIR / "policy.yaml"

# Fixed clock for recorded runs so site/data does not churn between machines.
RECORDED_AT = "2026-10-29T15:00:00Z"
