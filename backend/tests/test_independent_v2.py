"""Independent v2. The file is hashed before this module scores it.

This test does not require a passing score. It refuses to score a file that
no longer matches qa/INDEPENDENT_V2.sha256, and it records every miss.
"""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app.agent.engine import Agent
from app.commerce.routed import RoutedCommerce
from app.config import Settings
from app.db import configure, init_schema, session
from app.kb.index import SearchIndex
from app.kb.ingest import seed_knowledge
from app.seed.store import seed_store

ROOT = Path("/workspace")
SUITE = ROOT / "qa" / "independent_v2.json"
HASH_FILE = ROOT / "qa" / "INDEPENDENT_V2.sha256"
RAW = ROOT / "qa" / "independent_v2_results.json"
V1 = ROOT / "qa" / "independent_v1.json"
SEALED = ROOT / "qa" / "sealed.json"

_spec = importlib.util.spec_from_file_location("independent_v1_scorer", Path(__file__).with_name("test_independent_v1.py"))
_v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v1)


def _digest() -> str:
    return hashlib.sha256(SUITE.read_bytes()).hexdigest()


def _turns(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {turn.strip().lower() for case in payload["cases"] for turn in case["turns"]}


def test_independent_v2_file_is_frozen():
    recorded = HASH_FILE.read_text(encoding="utf-8").split()[0]
    assert recorded == _digest()
    mine = _turns(SUITE)
    assert not (mine & _turns(V1))
    assert not (mine & _turns(SEALED))


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    recorded = HASH_FILE.read_text(encoding="utf-8").split()[0]
    if recorded != _digest():
        pytest.fail("qa/independent_v2.json does not match qa/INDEPENDENT_V2.sha256.")
    path = tmp_path_factory.mktemp("independent_v2")
    url = f"sqlite:///{path}/keel.db"
    configure(url)
    init_schema()
    db = session()
    seed_store(db)
    seed_knowledge(db, path / "corpus")
    index = SearchIndex()
    index.load_or_build(db)
    settings = Settings(database_url=url, skip_traffic=True)
    agent = Agent(RoutedCommerce(settings), index, settings)
    return {"db": db, "agent": agent}


def test_independent_v2_is_scored_once(world):
    payload = json.loads(SUITE.read_text(encoding="utf-8"))
    cases = payload["cases"]
    attacks = [case for case in cases if case["category"] == "attack"]
    assert len(cases) >= 120
    assert len(attacks) >= 30
    results = [_v1.score_case(world, case) for case in cases]
    summary = _v1.summarize(results)
    RAW.write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    assert summary["cases"] == len(cases)
