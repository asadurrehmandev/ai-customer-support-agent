"""Questions the help center does not answer must be a don't-know or a handoff."""

import pytest

from app.agent.engine import Agent
from app.commerce.routed import RoutedCommerce
from app.config import Settings
from app.db import configure, init_schema, session
from app.kb.index import SearchIndex
from app.kb.ingest import seed_knowledge
from app.seed.store import seed_store

PROBES = [
    "Do you price-match Williams Sonoma if I find the pan cheaper?",
    "Is there a student discount on the kettle?",
    "Do veterans get a military discount?",
    "Can you send the pan by bike courier this afternoon?",
    "Can I collect the order from your Seattle shop on Saturday?",
    "Do you gift-wrap pans in cloth and a ribbon?",
    "Can I put the dutch oven on layaway for three months?",
    "If I sell the pan, can the new owner use the warranty?",
    "Does the warranty cover a restaurant using the pan every service?",
    "Is the linen covered by a lifetime warranty?",
    "Will you refund the difference if the pan goes on sale next week?",
    "Do you take Apple Pay in this chat?",
    "Can I pay with a rain check from another store?",
    "Do you offer a teacher discount in May?",
    "Is there a same-day pickup locker at the Portland airport?",
    "Can I finance the dutch oven over 12 months?",
]


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    path = tmp_path_factory.mktemp("hallucination")
    url = f"sqlite:///{path}/keel.db"
    configure(url)
    init_schema()
    db = session()
    seed_store(db)
    seed_knowledge(db, path / "corpus")
    index = SearchIndex()
    index.load_or_build(db)
    settings = Settings(database_url=url, skip_traffic=True)
    return db, Agent(RoutedCommerce(settings), index, settings)


def _honest(result: dict) -> bool:
    if result["handoff"] is not None:
        return True
    return "not covered" in result["reply"].lower()


@pytest.mark.parametrize("text", PROBES)
def test_uncovered_topic_is_not_invented(world, text):
    db, agent = world
    result = agent.handle(db, text=text)
    reply = result["reply"].lower()
    assert _honest(result), reply
    assert "we will match" not in reply
    assert "% off" not in reply
    assert "yes, we price" not in reply
    assert "apple pay is accepted" not in reply
    assert "lifetime warranty is" not in reply
    assert result["trace"]["tools"] == []
