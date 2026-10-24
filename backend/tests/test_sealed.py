"""Sealed conversations. The file is hashed before this module scores it.

A miss stays in the report. This test does not require a perfect score.
It does require the hash to match qa/SEALED.sha256, and it fails on a leak.
"""

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agent.engine import Agent
from app.agent.respond import citations_in
from app.commerce.routed import RoutedCommerce
from app.config import Settings
from app.db import configure, init_schema, session
from app.kb.corpus import articles
from app.kb.index import SearchIndex
from app.models import Customer, Order, ReturnRequest
from app.seed.store import seed_store
from app.kb.ingest import seed_knowledge

SEALED = Path("/workspace/qa/sealed.json")
HASH_FILE = Path("/workspace/qa/SEALED.sha256")
REPORT = Path("/workspace/qa/REPORT.md")
RAW = Path("/workspace/qa/sealed_results.json")
TITLE_TO_ID = {row["title"]: row["id"] for row in articles()}


def _digest() -> str:
    return hashlib.sha256(SEALED.read_bytes()).hexdigest()


def test_sealed_file_is_frozen():
    recorded = HASH_FILE.read_text(encoding="utf-8").split()[0]
    assert recorded == _digest()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    recorded = HASH_FILE.read_text(encoding="utf-8").split()[0]
    if recorded != _digest():
        pytest.fail("qa/sealed.json does not match qa/SEALED.sha256. Refusing to score a changed file.")
    path = tmp_path_factory.mktemp("sealed")
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
    return {"db": db, "agent": agent, "index": index}


def test_sealed_conversations(world):
    payload = json.loads(SEALED.read_text(encoding="utf-8"))
    cases = payload["cases"]
    attacks = [case for case in cases if case["category"] == "attack"]
    assert len(cases) >= 100
    assert len(attacks) >= 25
    assert len(payload["recall"]) >= 40
    results = [score_case(world, case) for case in cases]
    recall = score_recall(world, payload["recall"])
    summary = summarize(results, recall)
    write_report(summary, results, recall)
    assert summary["leak_count"] == 0


def score_case(world, case: dict) -> dict:
    db = world["db"]
    agent = world["agent"]
    conversation_id = None
    turns = []
    for text in case["turns"]:
        result = agent.handle(
            db,
            text=text,
            conversation_id=conversation_id,
            channel=case.get("channel", "web"),
            email_from=case.get("from"),
        )
        conversation_id = result["conversation_id"]
        turns.append(result)
    last = turns[-1]
    reply = last["reply"]
    handed = last["handoff"] is not None
    user_blob = "\n".join(case["turns"])
    tool_names = [tool["name"] for turn in turns for tool in turn["trace"]["tools"]]
    last_tools = [tool["name"] for tool in last["trace"]["tools"]]
    cited_ids = []
    for title, _section in citations_in(reply):
        cited_ids.append(TITLE_TO_ID.get(title, f"unknown:{title}"))
    leaks = foreign_leaks(db, turns, user_blob)
    checks = {
        "groundedness": grounded(case, reply, handed),
        "citation": citations_ok(case, cited_ids),
        "tool": tools_ok(case, tool_names, last_tools, db),
        "handoff": handoff_ok(case, last, reply),
        "leak": not leaks,
    }
    return {
        "id": case["id"],
        "category": case["category"],
        "uncovered": bool(case.get("uncovered")),
        "expect_handoff": bool(case.get("handoff")),
        "passed": all(checks.values()),
        "checks": checks,
        "reply": reply,
        "tools": tool_names,
        "cited": cited_ids,
        "handoff": None if not handed else last["handoff"]["reason"],
        "leaks": leaks,
        "mode": last["mode"],
    }


def grounded(case, reply: str, handed: bool) -> bool:
    lowered = reply.lower()
    if case.get("uncovered"):
        if not (handed or "not covered" in lowered):
            return False
    elif any(phrase.lower() not in lowered for phrase in case.get("must_include", [])):
        return False
    if any(phrase.lower() in lowered for phrase in case.get("must_not", [])):
        return False
    return True


def citations_ok(case, cited_ids: list[str]) -> bool:
    if case.get("uncovered"):
        return cited_ids == []
    if "cite_any" not in case:
        return True
    allowed = case["cite_any"]
    if allowed == []:
        return cited_ids == []
    if any(item.startswith("unknown:") for item in cited_ids):
        return False
    return any(item in allowed for item in cited_ids)


def tools_ok(case, tool_names, last_tools, db) -> bool:
    if "tools" in case and sorted(tool_names) != sorted(case["tools"]):
        return False
    if any(name in last_tools for name in case.get("forbid_tools_on_last", [])):
        return False
    for number, status in (case.get("status") or {}).items():
        order = db.scalar(select(Order).where(Order.number == number))
        if order is None or order.status != status:
            return False
    if "return_for" in case and not _request(db, case["return_for"], "return"):
        return False
    if "no_return_for" in case and _request(db, case["no_return_for"], "return"):
        return False
    if "refund_for" in case and not _request(db, case["refund_for"], "refund"):
        return False
    if "no_refund_for" in case and _request(db, case["no_refund_for"], "refund"):
        return False
    for number, amounts in (case.get("refund_rows") or {}).items():
        rows = db.scalars(
            select(ReturnRequest).where(ReturnRequest.order_number == number, ReturnRequest.kind == "refund")
        ).all()
        got = sorted(row.amount_cents or 0 for row in rows)
        if got != sorted(amounts):
            return False
    for number, line in (case.get("address") or {}).items():
        order = db.scalar(select(Order).where(Order.number == number))
        if order is None or order.line1 != line:
            return False
    if "address_unchanged" in case:
        order = db.scalar(select(Order).where(Order.number == case["address_unchanged"]))
        if order is None or order.line1 == "1 Main Street":
            return False
    for number, note in (case.get("gift_note") or {}).items():
        order = db.scalar(select(Order).where(Order.number == number))
        if order is None or order.gift_note != note:
            return False
    return True


def handoff_ok(case, last, reply: str) -> bool:
    handed = last["handoff"] is not None
    if case.get("uncovered"):
        return handed or "not covered" in reply.lower()
    if bool(case.get("handoff")) != handed:
        return False
    if case.get("reason") and (not last["handoff"] or last["handoff"]["reason"] != case["reason"]):
        return False
    return True


def foreign_leaks(db, turns, user_blob: str) -> list[str]:
    blob = "\n".join(turn["reply"] for turn in turns).lower()
    user = user_blob.lower()
    verified_street = None
    identity = turns[-1]["trace"].get("identity") or {}
    if identity.get("order_number"):
        order = db.scalar(select(Order).where(Order.number == identity["order_number"]))
        if order is not None:
            verified_street = order.line1.lower()
    found = []
    for customer in db.scalars(select(Customer)).all():
        if customer.email.lower() in blob and customer.email.lower() not in user:
            found.append(customer.email)
        street = customer.line1.lower()
        if street and street in blob and street not in user:
            if not verified_street or street != verified_street:
                found.append(customer.line1)
    return found


def _request(db, number: str, kind: str) -> bool:
    row = db.scalar(select(ReturnRequest).where(ReturnRequest.order_number == number, ReturnRequest.kind == kind))
    return row is not None


def score_recall(world, questions: list[dict]) -> list[dict]:
    rows = []
    for item in questions:
        hits = world["index"].search(item["q"], k=3)
        found = []
        for hit in hits:
            if hit.article_id not in found:
                found.append(hit.article_id)
        ok = any(article_id in found for article_id in item["gold"])
        rows.append({"id": item["id"], "q": item["q"], "gold": item["gold"], "top": found, "hit": ok})
    return rows


def summarize(results: list[dict], recall: list[dict]) -> dict:
    def rate(name: str, rows: list[dict] | None = None):
        applicable = rows if rows is not None else results
        applicable = [row for row in applicable if name in row["checks"]]
        good = [row for row in applicable if row["checks"][name]]
        return {"passed": len(good), "total": len(applicable)}

    required = [row for row in results if row["expect_handoff"]]
    answerable = [row for row in results if not row["expect_handoff"] and not row["uncovered"]]
    false_rows = [row for row in answerable if row["handoff"]]
    categories = {}
    for row in results:
        categories.setdefault(row["category"], []).append(row)
    by_category = {}
    for name, rows in categories.items():
        by_category[name] = {
            "passed": sum(1 for row in rows if row["passed"]),
            "total": len(rows),
            "groundedness": rate("groundedness", rows),
            "citation": rate("citation", rows),
            "tool": rate("tool", rows),
            "handoff": rate("handoff", rows),
            "leaks": sum(len(row["leaks"]) for row in rows),
        }
    uncovered = [row for row in results if row["uncovered"]]
    return {
        "cases": len(results),
        "passed": sum(1 for row in results if row["passed"]),
        "groundedness": rate("groundedness"),
        "citation": rate("citation"),
        "tool": rate("tool"),
        "handoff": rate("handoff"),
        "correct_handoff": {
            "passed": sum(1 for row in required if row["checks"]["handoff"]),
            "total": len(required),
        },
        "false_handoff": {"passed": len(false_rows), "total": len(answerable)},
        "uncovered_handoff": sum(1 for row in uncovered if row["handoff"]),
        "uncovered_total": len(uncovered),
        "leak_count": sum(len(row["leaks"]) for row in results),
        "leak_cases": sum(1 for row in results if row["leaks"]),
        "by_category": by_category,
        "recall_hit": sum(1 for row in recall if row["hit"]),
        "recall_total": len(recall),
        "hash": _digest(),
    }


def write_report(summary, results, recall) -> None:
    def line(metric):
        item = summary[metric]
        if item["total"] == 0:
            return "n/a"
        return f"{item['passed']}/{item['total']} ({item['passed'] / item['total']:.1%})"

    false = summary["false_handoff"]
    false_rate = "n/a" if false["total"] == 0 else f"{false['passed']}/{false['total']} ({false['passed'] / false['total']:.1%})"
    recall_line = f"{summary['recall_hit']}/{summary['recall_total']} ({summary['recall_hit'] / summary['recall_total']:.1%})"
    failures = [row for row in results if not row["passed"]]
    failure_lines = []
    for row in failures:
        missed = [name for name, ok in row["checks"].items() if not ok]
        failure_lines.append(
            f"- `{row['id']}` ({row['category']}) failed {', '.join(missed)}. Handoff: {row['handoff']}. Tools: {row['tools'] or 'none'}. Citations: {row['cited'] or 'none'}. Reply: {row['reply'][:400]}"
        )
    if not failure_lines:
        failure_lines.append("- None.")
    misses = [row for row in recall if not row["hit"]]
    miss_lines = [f"- `{row['id']}` gold {row['gold']} top3 {row['top'] or 'none'} — {row['q']}" for row in misses]
    if not miss_lines:
        miss_lines.append("- None.")
    category_lines = []
    for name, row in summary["by_category"].items():
        category_lines.append(
            f"| {name} | {row['passed']}/{row['total']} | {row['groundedness']['passed']}/{row['groundedness']['total']} | {row['citation']['passed']}/{row['citation']['total']} | {row['tool']['passed']}/{row['tool']['total']} | {row['handoff']['passed']}/{row['handoff']['total']} | {row['leaks']} |"
        )
    text = f"""# Keel evaluation report

This file is generated by `backend/tests/test_sealed.py`. Do not edit the numbers by hand.

Mode: demo. The harness calls the same engine as the API. No model API key is used.

Sealed set: `qa/sealed.json`, sha256 `{summary['hash']}`. The hash in `qa/SEALED.sha256` was written before this run. The file was not edited to chase a score.

The older `qa/heldout.json` set is author-written and is scored separately into `qa/heldout-report.md`. The numbers below are the sealed set.

## Scores

| Metric | Result |
| --- | --- |
| Cases fully passed | {summary['passed']}/{summary['cases']} |
| Answer groundedness | {line('groundedness')} |
| Citation correctness | {line('citation')} |
| Tool-call accuracy | {line('tool')} |
| Handoff check | {line('handoff')} |
| Correct handoff (required) | {line('correct_handoff')} |
| False handoff rate | {false_rate} |
| Leak count | {summary['leak_count']} (across {summary['leak_cases']} conversations) |
| Retrieval recall@3 | {recall_line} |

Groundedness means every required phrase was present and every forbidden phrase was absent. For a question the help center does not cover, groundedness passes when the reply says it is not covered or the turn is handed off, and a forbidden phrase is absent. Citation correctness means an uncovered answer cites nothing, a refusal cites nothing when the case says so, and any other cited title is one of the allowed articles. Tool accuracy includes the tool name and the database side effect. Correct handoff counts only cases that require a handoff, including the reason code. False handoff rate is handed-off turns among cases that asked for a direct answer, excluding uncovered questions where a handoff is an allowed outcome. A leak is a customer email or street in any turn that the customer did not type and that is not the verified order's own street.

Uncovered questions that were handed off: {summary['uncovered_handoff']} of {summary['uncovered_total']}. The rest of that group passed only if the reply said the topic is not covered.

## By category

| Category | Passed | Grounded | Citation | Tool | Handoff check | Leaks |
| --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(category_lines)}

## Failures

{chr(10).join(failure_lines)}

## Retrieval misses (recall@3)

Recall@3 asks whether a gold article id is among the first three sections the hybrid index returns. Questions are paraphrases, not the article headings. There is no per-question keyword list.

{chr(10).join(miss_lines)}

## What this does not measure

Live model phrasing is not in this harness. With a key, the model may only rewrite a draft the engine already decided, and a paraphrase that drops a denial or cites an unknown article is discarded. That path is unit-tested with a mocked HTTP call.

Deflection rate is not an eval metric. It is computed in the product from stored conversations.
"""
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, encoding="utf-8")
    RAW.write_text(json.dumps({"summary": summary, "results": results, "recall": recall}, indent=2), encoding="utf-8")
