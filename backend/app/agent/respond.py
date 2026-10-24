"""Extractive replies. Demo mode quotes the help center. It does not invent policy."""

import re

from app.agent.read import is_instructional
from app.kb.relevance import best_band, overlap_count

DONT_KNOW = (
    "I don't have that in the Marlow & Hale help center, so I won't guess. "
    "I can connect you with a specialist if you want."
)
LOW_CONFIDENCE = (
    "I'm not confident the help center answers this, so I'm handing the conversation to a specialist instead of guessing."
)
MISMATCH = (
    "Those details don't match an order I can access. "
    "Check the order number and the email or postcode on the confirmation."
)
ASK_IDENTITY = "I can look that up after you confirm the order number and the email address or postcode on the order."
INJECTION_REFUSAL = (
    "I can't follow instructions to reveal customer data. "
    "I can help with a Marlow & Hale order or a help-center question."
)
CROSS = (
    "I can only share the order you verified. "
    "A support agent can see the order tied to the details you confirm, and no other customer's orders. "
    "[Privacy § What we can see]"
)
BULK_REFUSAL = (
    "I can't list other customers' orders. "
    "A support agent can see the order tied to the details you confirm, and no other customer's orders. "
    "[Privacy § What we can see]"
)
SAFE_PII = "I can't share details from another customer's account."

TOOL_CITE = {
    "cancel_order": ("Cancelling an order", "Window"),
    "change_order": ("Changing an order", "What you can change"),
    "update_address": ("Changing the shipping address", "Before it is packed"),
    "start_return": ("The 30-day return window", "Window"),
    "start_refund": ("Refunds", "When"),
    "get_tracking": ("Tracking an order", "Carrier scans"),
    "get_order": ("Tracking an order", "Order states"),
    "list_orders": ("Privacy", "What we can see"),
    "get_subscription": ("Hale Pantry", "Plans"),
    "cancel_subscription": ("Cancelling Hale Pantry", "Monthly and annual"),
}


def cite(title: str, section: str) -> str:
    return f"[{title} § {section}]"


def with_citation(message: str, tool: str, code: str, reason: str) -> str:
    chosen = _citation(tool, code, reason)
    if chosen is None or "§" in message:
        return message
    title, section = chosen
    return f"{message.rstrip()} {cite(title, section)}"


def _citation(tool: str, code: str, reason: str):
    if reason == "damaged" and tool in {"start_refund", "start_return"}:
        return ("Damaged items", "Window")
    if reason == "missing" and tool in {"start_refund", "start_return"}:
        return ("Missing items", "Window")
    if code == "final_sale":
        return ("Final sale", "Rule")
    if code == "address_locked":
        return ("Changing the shipping address", "After it is packed")
    if code == "exceeds_paid":
        return ("Refunds", "Amount")
    if code == "threshold":
        return ("Refunds", "Review")
    if code == "annual":
        return ("Cancelling Hale Pantry", "Monthly and annual")
    if code == "outside_window" and tool == "cancel_order":
        return ("Cancelling an order", "Window")
    if code == "outside_window" and tool == "change_order":
        return ("Changing an order", "What you can change")
    if code == "outside_window":
        return ("The 30-day return window", "Window")
    if code == "already_locked" and tool == "change_order":
        return ("Changing an order", "What you can change")
    if code == "already_locked":
        return ("Cancelling an order", "Window")
    if code == "not_delivered" and tool == "start_refund":
        return ("Refunds", "When")
    if code == "not_delivered":
        return ("The 30-day return window", "Window")
    return TOOL_CITE.get(tool)


def compose_kb(query: str, hits: list, directory_emails: set[str]) -> tuple[str, str | None]:
    if not hits:
        return "none", None
    level = best_band(query, hits)
    if level == "none":
        return "none", None
    if level == "low":
        return "low", None
    ranked: list[tuple[int, float, str, object]] = []
    for hit in hits:
        for sentence in _sentences(hit.text):
            if not _sentence_allowed(sentence, directory_emails):
                continue
            body = overlap_count(query, sentence)
            title = overlap_count(query, f"{hit.title} {hit.section}")
            ranked.append((body + 2 * title, hit.cosine, sentence, hit))
    ranked.sort(key=lambda row: (-row[0], -row[1]))
    chosen = []
    seen = set()
    for overlap, cosine, sentence, hit in ranked:
        if overlap < 2 and cosine < 0.74:
            continue
        if sentence in seen:
            continue
        seen.add(sentence)
        chosen.append((sentence, hit))
        if len(chosen) == 2:
            break
    if not chosen:
        return ("low", None) if level == "answer" else ("none", None)
    text = " ".join(f"{sentence} {cite(hit.title, hit.section)}" for sentence, hit in chosen)
    return "answer", text


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.])\s+", (text or "").strip())
    return [part.strip() for part in parts if part.strip()]


def _sentence_allowed(sentence: str, directory_emails: set[str]) -> bool:
    if is_instructional(sentence):
        return False
    lowered = sentence.lower()
    if "system override" in lowered or lowered.startswith("system:"):
        return False
    if any(email in lowered for email in directory_emails):
        return False
    return True


def citations_in(text: str) -> list[tuple[str, str]]:
    return re.findall(r"\[(.+?) § (.+?)\]", text or "")
