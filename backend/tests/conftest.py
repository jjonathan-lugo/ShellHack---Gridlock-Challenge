import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

DATA_DIR = REPO_ROOT / "data" / "processed"


@pytest.fixture(scope="session")
def projects():
    with open(DATA_DIR / "projects.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def spreadsheet_overlaps():
    """The overlap table exported from Projects_Overlaps.xlsx — our ground truth."""
    with open(DATA_DIR / "overlaps.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def utilities(projects):
    desc = [p for p in projects if "Dominion" in p["utility"]]
    gpc = [p for p in projects if p not in desc]
    return desc, gpc
