"""Read a customer message. Routing is deterministic so a model cannot be talked into a tool call."""

import re
from dataclasses import dataclass

ORDER_HINT = re.compile(r"mh[-\s]?\d{5}", re.I)
POLICY_Q = re.compile(
    r"\b(how long|how much|how do i|how does|how should|how many|what is your|what's your|what are your|what is the|what's the|do you|does the|policy|explain|when is|is there a)\b",
    re.I,
)
HUMAN = re.compile(
    r"\b(talk to (a )?(human|person|someone)|real person|transfer me|speak to (a )?(person|human)|customer service representative|hand me to)\b"
    r"|\b(want|need|get me) (a )?specialist\b",
    re.I,
)
YES = re.compile(r"^\s*(yes|yes please|please do|yeah|yep|sure|ok|okay)\s*[.!]?\s*$", re.I)
INSTRUCT = re.compile(
    r"(ignore (all |any |the )?(previous|prior|above)|ignore (the |our )?policy|"
    r"disregard (the |our )?policy|system prompt|you are now|print every|"
    r"list all (of the )?(customer|email)|dump (the )?(database|emails)|developer mode|"
    r"jailbreak|reveal (all |every )?(customer|email|order)|do not follow|"
    r"pretend (that )?you verified|skip verification|ignore verification)",
    re.I,
)
SOCIAL = re.compile(
    r"(i am the ceo|i'm the ceo|this is the ceo|fraud team|as an admin|i authorize you|"
    r"i'm with the fraud|skip verification|ignore verification)",
    re.I,
)
EVERYONE = re.compile(
    r"(every customer|all customers|all emails|other customer|someone else|entire database|all orders in the)",
    re.I,
)
SAFETY = ("injured", "injury", "burn", "burned", "burning", "fire", "allergic", "allergy", "bleeding", "swallowed", "chok", "recall", "poison", "hospital", "clinic")
CHARGE = ("chargeback", "charge back", "charge-back", "disputed the charge", "dispute the charge", "opened a dispute", "called my bank", "calling my bank", "call my bank", "opening a chargeback")
LEGAL = ("lawyer", "attorney", "lawsuit", "sue ", "suing", "legal action", "my solicitor")
STRONG = ("furious", "scam", "incompetent", "disgusting", "worst company", "idiot", "useless")
MEDIUM = ("ridiculous", "unacceptable", "angry", "disgusted", "outraged", "terrible")

ACCOUNT_INTENTS = {
    "cancel_order",
    "edit_order",
    "update_address",
    "start_return",
    "start_refund",
    "tracking",
    "order_status",
    "list_orders",
    "subscription_lookup",
    "cancel_subscription",
}


@dataclass
class Reading:
    intent: str
    sentiment: str
    handoff_reason: str | None
    injection: bool
    social: bool
    asks_for_everyone: bool
    query: str


def is_instructional(text: str) -> bool:
    return bool(INSTRUCT.search(text or ""))


def substantive(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [part for part in parts if part.strip() and not is_instructional(part) and not SOCIAL.search(part)]
    return " ".join(kept).strip()


def sentiment_of(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in STRONG) or "ridiculous" in lowered:
        return "angry"
    if sum(word in lowered for word in MEDIUM) >= 2:
        return "angry"
    if any(word in lowered for word in MEDIUM) or "frustrated" in lowered or "annoyed" in lowered:
        return "frustrated"
    return "calm"


def task_intent(text: str, verified: bool) -> str:
    lowered = text.lower()
    has_order = bool(ORDER_HINT.search(lowered))
    policy_q = bool(POLICY_Q.search(lowered))
    bound = has_order or verified
    if policy_q and not has_order:
        return "kb"
    if re.search(r"gift note|gift-note|quantity", lowered) and (bound or "order" in lowered):
        return "edit_order"
    if "address" in lowered:
        if re.search(r"\b(change|update|set|correct|switch)\b", lowered) and (bound or "order" in lowered):
            return "update_address"
        if policy_q and not has_order:
            return "kb"
        if re.search(r"\b(what is|what's|give me|show|read|tell me|shipping address)\b", lowered):
            return "order_status"
        if bound:
            return "update_address"
    if re.search(r"\b(hale pantry|subscription)\b", lowered) or "my plan" in lowered:
        if "cancel" in lowered and bound and not lowered.strip().startswith("how"):
            return "cancel_subscription"
        if bound and not policy_q:
            return "subscription_lookup"
        return "kb"
    if "refund" in lowered or (re.search(r"\b(missing|damaged|broken|cracked)\b", lowered) and has_order):
        if policy_q and not has_order:
            return "kb"
        return "start_refund"
    if re.search(r"\breturn\b", lowered):
        if policy_q and not has_order:
            return "kb"
        if has_order or (verified and re.search(r"\b(want|start|please|would like)\b", lowered)):
            return "start_return"
        return "kb"
    if "cancel" in lowered:
        if policy_q and not has_order:
            return "kb"
        if bound or "my order" in lowered or "the order" in lowered or "order" in lowered:
            return "cancel_order"
        return "kb"
    if re.search(r"\b(change|edit|modify)\b", lowered) and has_order:
        return "edit_order"
    if re.search(r"\b(track|tracking|where is|where are)\b", lowered):
        if policy_q and not has_order and "my" not in lowered:
            return "kb"
        return "tracking"
    if re.search(r"\bstatus\b", lowered):
        return "order_status"
    if "my orders" in lowered or "all my orders" in lowered:
        return "list_orders"
    return "kb"


def read_message(text: str, *, verified: bool, offered_handoff: bool) -> Reading:
    raw = text or ""
    injection = bool(INSTRUCT.search(raw))
    social = bool(SOCIAL.search(raw))
    everyone = bool(EVERYONE.search(raw))
    sentiment = sentiment_of(raw)
    query = substantive(raw) or raw
    lowered = raw.lower()
    handoff = None
    if any(word in lowered for word in SAFETY):
        handoff = "safety"
        intent = "safety"
    elif any(word in lowered for word in CHARGE):
        handoff = "chargeback"
        intent = "chargeback"
    elif any(word in lowered for word in LEGAL):
        handoff = "legal"
        intent = "legal"
    elif sentiment == "angry":
        handoff = "angry"
        intent = task_intent(query, verified)
    elif HUMAN.search(raw) or (offered_handoff and YES.match(raw)):
        handoff = "customer_requested"
        intent = "human"
    else:
        intent = task_intent(query, verified)
    if everyone and intent in ACCOUNT_INTENTS | {"kb"}:
        intent = "refuse_bulk"
    if injection and not substantive(raw):
        intent = "refuse_injection"
    return Reading(intent, sentiment, handoff, injection, social, everyone, query if intent != "refuse_injection" else query)
