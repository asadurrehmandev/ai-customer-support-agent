"""Extractive replies. Demo mode quotes the help center. It does not invent policy."""

import re

from app.agent.read import INSTRUCT, is_instructional, normalize_untrusted
DONT_KNOW = (
    "That is not covered in the Marlow & Hale help center, so I won't guess. "
    "I can connect you with a specialist if you want."
)
SWITCH = (
    "This conversation is already verified for one order. "
    "I can't switch it to another customer."
)
LOW_CONFIDENCE = (
    "I'm not confident the help center answers this, so I'm handing the conversation to a specialist instead of guessing."
)
HEDGE_LEAD = "I think this is the right section, though I'm not certain it covers every part of the question."
HEDGE_OFFER = "A specialist can confirm if you'd like a person to take it."
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
    body = message.rstrip()
    if body.startswith(("I ", "On the ", "The Hale", "Order ", "There is")):
        return f"{body} {cite(title, section)}"
    return f"Here is the rule that applies. \"{body}\" {cite(title, section)}"


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
    from app.kb.relevance import decide
    from app.kb.span import select_span

    decision = decide(query, hits)
    if decision.level == "none":
        return "none", None
    if decision.level == "low":
        return "low", None
    hit = hits[0]
    span = select_span(query, hit.text, directory_emails)
    if not span.quote:
        return "none", None
    citation = cite(hit.title, hit.section)
    if span.unmet:
        shown = ", ".join(span.unmet[:3])
        body = (
            f"The help center doesn't cover {shown}. "
            f"The closest section says: \"{span.quote}\" {citation} "
            f"I'm handing this to a specialist rather than guessing about {shown}."
        )
        return "partial", body
    if decision.level == "hedge":
        body = f"{HEDGE_LEAD} {_lead(query)} \"{span.quote}\" {citation} {HEDGE_OFFER}"
        return "hedge", body
    return "answer", f"{_lead(query)} \"{span.quote}\" {citation}"


def pick_quote(query: str, hits: list, directory_emails: set[str]):
    """Quote the winning section, not a second article that merely shares a word.

    A duration question can quote the top section when that section states a
    number of days or hours. Other paraphrases still have to clear the gate.
    """
    from app.kb.relevance import _DURATION_A, _DURATION_Q, hit_band

    answer_hits = [hit for hit in hits if hit_band(query, hit) == "answer"]
    chosen = max(answer_hits, key=lambda hit: hit.rerank) if answer_hits else None
    if chosen is None and hits and _DURATION_Q.search(query or "") and _DURATION_A.search(hits[0].text or ""):
        adjusted = hits[0].rerank + 6.0
        cosine = hits[0].cosine
        if adjusted >= 1.0 or (adjusted >= -1.0 and cosine >= 0.70) or (adjusted >= 0.5 and cosine >= 0.62):
            chosen = hits[0]
    if chosen is None:
        return None
    text = _section_quote(chosen.text, directory_emails)
    if not text:
        return None
    return text, chosen


def _section_quote(text: str, directory_emails: set[str]) -> str | None:
    sentences = [sentence for sentence in quotable_sentences(text) if _sentence_allowed(sentence, directory_emails)]
    if not sentences:
        return None
    return " ".join(sentence if sentence.endswith(".") else f"{sentence}." for sentence in sentences)


def _lead(query: str) -> str:
    lowered = (query or "").lower()
    if any(phrase in lowered for phrase in ("how long", "how many", "window", "when can", "deadline")):
        return "Here is the window from the help center."
    if any(phrase in lowered for phrase in ("how much", "cost", "price", "fee", "charge")):
        return "Here is the figure from the help center."
    if lowered.startswith("how ") or " how " in f" {lowered} ":
        return "Here is how the help center describes it."
    return "Here is what the help center says."


def quotable_sentences(text: str) -> list[str]:
    cleaned = INSTRUCT.sub(". ", normalize_untrusted(text or ""))
    parts = re.split(r"(?<=[.])\s+", cleaned.strip())
    kept = []
    for part in parts:
        sentence = part.strip(" .")
        if sentence and not is_instructional(sentence):
            kept.append(sentence if sentence.endswith(".") else sentence)
    return kept


def _sentences(text: str) -> list[str]:
    return quotable_sentences(text)


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
