"""Hand-rolled state machine.

States, in order: read, guard, verify, tool, retrieve, answer, handoff.
The model is never allowed to choose a tool or to skip a guardrail. When a
key is present it may only rephrase a draft the engine already decided.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.llm import accept_paraphrase, phrase, safe_error
from app.agent.read import ACCOUNT_INTENTS, MUTATING_INTENTS, POLICY_Q, Reading, is_instructional, read_message
from app.agent.respond import (
    ASK_IDENTITY,
    BULK_REFUSAL,
    CROSS,
    DONT_KNOW,
    INJECTION_REFUSAL,
    LOW_CONFIDENCE,
    MISMATCH,
    SAFE_PII,
    SWITCH,
    compose_kb,
    with_citation,
)
from app.commerce.routed import RoutedCommerce
from app.config import Settings
from app.handoff.zendesk import ZendeskClient
from app.identity import factor_match, proof_email, proof_postcode
from app.models import Conversation, Customer, Csat, Message, Ticket, TraceRecord
from app.textutil import content_tokens, emails, money, nid, order_numbers, utcnow

ADDR_RE = re.compile(
    r"(?:\b(?:to|as)\s+)?(?P<line>\d{1,6}\s+[A-Za-z0-9.'-]+(?:\s+[A-Za-z0-9.'-]+){0,5}),\s*(?P<city>[A-Za-z][^,\n]{1,40}),\s*(?P<region>[A-Za-z]{2})\s+(?P<zip>\d{5})\b"
)
GIFT_RE = re.compile(r"gift note[:\s]+['\"](.+?)['\"]", re.I)
QTY_RE = re.compile(r"quantity(?:\s+to|\s+of)?\s+(\d+)", re.I)
AMOUNT_RE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]{1,2})?)")

HANDOFF_COPY = {
    "safety": "I'm handing this to a specialist now. If someone is hurt, contact local emergency services.",
    "chargeback": "I've handed this to a specialist because a bank dispute needs a person. I have not changed the order.",
    "legal": "I've handed this to a specialist to handle the legal question. I won't keep discussing it here.",
    "angry": "I'm going to hand this to a specialist so a person can take it from here.",
    "customer_requested": "I've handed this conversation to a specialist, with the transcript.",
    "vip": "This account is handled by a specialist. I've passed along the transcript.",
    "low_confidence": LOW_CONFIDENCE,
    "refund_threshold": "Refund requests over $75 are reviewed by a specialist before they are submitted. I have not submitted this one.",
    "annual_plan": "Cancelling an annual plan is handled by a specialist. I have not cancelled it.",
}


class Agent:
    def __init__(self, commerce: RoutedCommerce, index, settings: Settings):
        self.commerce = commerce
        self.index = index
        self.settings = settings

    def handle(
        self,
        session: Session,
        *,
        text: str,
        conversation_id: str | None = None,
        channel: str = "web",
        email_from: str | None = None,
        email_subject: str | None = None,
        llm_key: str | None = None,
    ) -> dict:
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValueError("Message is empty.")
        if len(cleaned) > 8000:
            raise ValueError("Message is too long.")
        conv = self._conversation(
            session,
            conversation_id=conversation_id,
            channel=channel,
            email_from=email_from,
            email_subject=email_subject,
        )
        customer_message = Message(id=nid("m_"), conversation_id=conv.id, role="customer", content=cleaned, created_at=utcnow())
        session.add(customer_message)
        session.flush()
        previous_intent = conv.last_intent
        reading = read_message(cleaned, verified=bool(conv.verified_customer_id), offered_handoff=conv.offered_handoff)
        trace: dict = {
            "states": ["read"],
            "intent": reading.intent,
            "sentiment": reading.sentiment,
            "injection": reading.injection,
            "social": reading.social,
            "retrieval": [],
            "tools": [],
            "guardrails": [],
            "identity": {"verified": bool(conv.verified_customer_id), "method": conv.verified_via, "order_number": conv.verified_order_number},
        }
        conv.sentiment = reading.sentiment
        conv.last_intent = reading.intent
        if reading.injection:
            trace["guardrails"].append({"rule": "prompt_injection", "decision": "ignore", "detail": "Message contained instructions. They were not followed."})
        if reading.social:
            trace["guardrails"].append({"rule": "social_engineering", "decision": "ignore", "detail": "A claimed role does not verify an account."})

        trace["states"].append("guard")
        if reading.handoff_reason:
            trace["guardrails"].append({"rule": reading.handoff_reason, "decision": "handoff", "detail": HANDOFF_COPY[reading.handoff_reason]})
            return self._finish(session, conv, content=HANDOFF_COPY[reading.handoff_reason], outcome="handoff", status="handed_off", trace=trace, handoff_reason=reading.handoff_reason, llm_key=llm_key, user_text=cleaned)

        trace["states"].append("verify")
        attempted = self._verify(session, conv, cleaned, channel, email_from, trace)
        if attempted == "mismatch":
            return self._finish(session, conv, content=MISMATCH, outcome="pending", status="open", trace=trace, llm_key=llm_key, user_text=cleaned)
        if attempted == "switch":
            trace["guardrails"].append({"rule": "identity", "decision": "switch_blocked", "detail": "A verified conversation cannot be moved to another customer."})
            return self._finish(session, conv, content=SWITCH, outcome="refused", status="resolved", trace=trace, llm_key=llm_key, user_text=cleaned)
        if attempted == "vip":
            trace["guardrails"].append({"rule": "vip", "decision": "handoff", "detail": HANDOFF_COPY["vip"]})
            return self._finish(session, conv, content=HANDOFF_COPY["vip"], outcome="handoff", status="handed_off", trace=trace, handoff_reason="vip", llm_key=llm_key, user_text=cleaned)

        if attempted == "ok" and reading.intent == "kb" and not POLICY_Q.search(cleaned):
            if previous_intent in ACCOUNT_INTENTS:
                reading.intent = previous_intent
                trace["intent"] = previous_intent
            elif order_numbers(cleaned) and (_identity_only(cleaned) or re.search(r"\b(read|show|check|see|open|pull|about|details)\b", cleaned, re.I)):
                reading.intent = "order_status"
                trace["intent"] = reading.intent

        if reading.intent == "refuse_injection":
            return self._finish(session, conv, content=INJECTION_REFUSAL, outcome="refused", status="resolved", trace=trace, llm_key=llm_key, user_text=cleaned)
        if reading.intent == "refuse_bulk":
            trace["guardrails"].append({"rule": "cross_customer", "decision": "block", "detail": "Bulk customer data request."})
            return self._finish(session, conv, content=BULK_REFUSAL, outcome="refused", status="resolved", trace=trace, llm_key=llm_key, user_text=cleaned)
        if reading.injection and reading.intent in MUTATING_INTENTS:
            trace["guardrails"].append({"rule": "prompt_injection", "decision": "block", "detail": "An instruction was mixed with an account change. The change was not run."})
            return self._finish(session, conv, content=INJECTION_REFUSAL, outcome="refused", status="resolved", trace=trace, llm_key=llm_key, user_text=cleaned)

        if reading.intent in ACCOUNT_INTENTS:
            target, blocked = self._target(conv, cleaned, trace)
            if blocked == "cross":
                trace["guardrails"].append({"rule": "cross_customer", "decision": "block", "detail": "Order is not the verified order."})
                return self._finish(session, conv, content=CROSS, outcome="refused", status="resolved", trace=trace, llm_key=llm_key, user_text=cleaned)
            if not conv.verified_customer_id or not target:
                return self._finish(session, conv, content=ASK_IDENTITY, outcome="pending", status="open", trace=trace, llm_key=llm_key, user_text=cleaned)
            trace["states"].append("tool")
            result = self._tool(session, conv, reading.intent, target, cleaned, request_id=customer_message.id)
            trace["tools"].append(
                {
                    "name": result.tool,
                    "arguments": _tool_args(reading.intent, target, cleaned),
                    "ok": result.ok,
                    "result": {"code": result.code, "message": result.message, **(result.data or {})},
                }
            )
            if result.handoff_reason:
                copy = result.message or HANDOFF_COPY.get(result.handoff_reason, HANDOFF_COPY["customer_requested"])
                copy = with_citation(copy, result.tool, result.code, _reason(cleaned))
                trace["guardrails"].append({"rule": result.handoff_reason, "decision": "handoff", "detail": copy})
                return self._finish(session, conv, content=copy, outcome="handoff", status="handed_off", trace=trace, handoff_reason=result.handoff_reason, llm_key=llm_key, user_text=cleaned)
            self._record_action(conv, f"{result.tool}:{'ok' if result.ok else result.code}")
            body = with_citation(result.message, result.tool, result.code, _reason(cleaned))
            trace["states"].append("answer")
            return self._finish(session, conv, content=body, outcome="answered", status="resolved", trace=trace, llm_key=llm_key, user_text=cleaned)

        trace["states"].append("retrieve")
        query = self.index.prepare(_followup_query(session, conv, reading.query or cleaned))
        hits = self.index.search(query, k=8)
        trace["retrieval"] = [hit.public() for hit in hits]
        directory = {email.lower() for email in session.scalars(select(Customer.email)).all() if email}
        level, drafted = compose_kb(query, hits, directory)
        trace["guardrails"].append({"rule": "grounding", "decision": level, "detail": f"Top cosine {hits[0].cosine:.3f}" if hits else "No chunks"})
        if level == "partial" and drafted:
            trace["states"].append("handoff")
            trace["guardrails"].append({"rule": "constraint", "decision": "handoff", "detail": "The section does not state the asked constraint."})
            return self._finish(session, conv, content=drafted, outcome="handoff", status="handed_off", trace=trace, handoff_reason="low_confidence", llm_key=llm_key, user_text=cleaned)
        if level == "hedge" and drafted:
            trace["states"].append("answer")
            return self._finish(session, conv, content=drafted, outcome="hedged", status="resolved", trace=trace, llm_key=llm_key, user_text=cleaned)
        if level == "low":
            trace["states"].append("handoff")
            return self._finish(session, conv, content=LOW_CONFIDENCE, outcome="handoff", status="handed_off", trace=trace, handoff_reason="low_confidence", llm_key=llm_key, user_text=cleaned)
        if level != "answer" or not drafted:
            conv.offered_handoff = True
            trace["states"].append("answer")
            return self._finish(session, conv, content=DONT_KNOW, outcome="unknown", status="resolved", trace=trace, llm_key=llm_key, user_text=cleaned)
        trace["states"].append("answer")
        return self._finish(session, conv, content=drafted, outcome="answered", status="resolved", trace=trace, llm_key=llm_key, user_text=cleaned)

    def _conversation(self, session, *, conversation_id, channel, email_from, email_subject) -> Conversation:
        if conversation_id:
            conv = session.get(Conversation, conversation_id)
            if conv is None:
                raise KeyError(conversation_id)
            conv.status = "open"
            return conv
        if channel == "email" and email_from:
            existing = session.scalar(
                select(Conversation).where(
                    Conversation.channel == "email",
                    Conversation.customer_email == email_from,
                    Conversation.status == "open",
                )
            )
            if existing is not None:
                return existing
        conv = Conversation(
            id=nid("c_"),
            channel=channel,
            status="open",
            outcome="pending",
            subject=email_subject,
            customer_email=email_from,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(conv)
        session.flush()
        return conv

    def _verify(self, session, conv, text, channel, email_from, trace) -> str | None:
        numbers = order_numbers(text)
        email = proof_email(text)
        if email is None and channel == "email" and email_from:
            email = email_from
        postcode = proof_postcode(text)
        if conv.verified_customer_id and numbers and numbers[-1] != conv.verified_order_number:
            return "switch"
        if conv.verified_customer_id:
            return None
        if not numbers or not (email or postcode):
            return None
        number = numbers[-1]
        order = self.commerce.get_order(session, number)
        email_ok, pc_ok = factor_match(order, email, postcode)
        if email and not email_ok:
            trace["identity"] = {"verified": False, "method": None, "order_number": None}
            trace["guardrails"].append({"rule": "identity", "decision": "mismatch", "detail": "Order number and email or postcode did not match."})
            return "mismatch"
        if postcode and not pc_ok:
            trace["identity"] = {"verified": False, "method": None, "order_number": None}
            trace["guardrails"].append({"rule": "identity", "decision": "mismatch", "detail": "Order number and email or postcode did not match."})
            return "mismatch"
        if not email_ok and not pc_ok:
            trace["identity"] = {"verified": False, "method": None, "order_number": None}
            trace["guardrails"].append({"rule": "identity", "decision": "mismatch", "detail": "Order number and email or postcode did not match."})
            return "mismatch"
        method = "order+email" if email_ok and not pc_ok else "order+postcode" if pc_ok and not email_ok else "order+email+postcode"
        conv.verified_customer_id = order.customer_id
        conv.verified_order_number = order.number
        conv.verified_via = method
        conv.customer_email = order.email
        conv.customer_name = order.customer_name
        trace["identity"] = {"verified": True, "method": method, "order_number": order.number}
        trace["guardrails"].append({"rule": "identity", "decision": "verified", "detail": method})
        if order.vip:
            return "vip"
        return "ok"

    def _target(self, conv: Conversation, text: str, trace: dict) -> tuple[str | None, str | None]:
        refs = order_numbers(text)
        if not conv.verified_customer_id:
            return (refs[-1] if refs else None), None
        if not refs:
            return conv.verified_order_number, None
        target = refs[-1]
        if target == conv.verified_order_number:
            return target, None
        # A successful verify in this turn rebinds before _target. A different
        # order here did not pass factors.
        if trace["identity"].get("verified") and trace["identity"].get("order_number") == target:
            return target, None
        return target, "cross"

    def _tool(self, session, conv, intent, number, text, request_id: str | None = None):
        reason = _reason(text)
        if intent == "cancel_order":
            return self.commerce.cancel_order(session, number, "customer request", request_id=request_id)
        if intent == "update_address":
            return self.commerce.update_address(session, number, _address(text))
        if intent == "edit_order":
            return self.commerce.change_order(session, number, _changes(text))
        if intent == "start_return":
            return self.commerce.start_return(session, number, reason)
        if intent == "start_refund":
            return self.commerce.start_refund(session, number, _amount(text), reason, request_id=request_id)
        if intent == "tracking":
            return self.commerce.get_tracking(session, number)
        if intent == "order_status":
            return self.commerce.describe_order(session, number)
        if intent == "list_orders":
            orders = self.commerce.list_orders(session, conv.verified_customer_id)
            if not orders:
                from app.commerce.types import ActionResult

                return ActionResult(True, "ok", "I don't see any orders on the verified account.", data={"orders": []}, tool="list_orders")
            bits = ", ".join(f"{order.number} ({order.status})" for order in orders)
            from app.commerce.types import ActionResult

            return ActionResult(True, "ok", f"On the verified account I can see: {bits}.", data={"orders": [order.number for order in orders]}, tool="list_orders")
        if intent == "subscription_lookup":
            return self.commerce.describe_subscription(session, conv.verified_customer_id, email=conv.customer_email)
        if intent == "cancel_subscription":
            return self.commerce.cancel_subscription(session, conv.verified_customer_id, request_id=request_id)
        from app.commerce.types import ActionResult

        return ActionResult(False, "unsupported", "I can't take that action from this chat.", tool=intent)

    def _finish(self, session, conv, *, content, outcome, status, trace, user_text, handoff_reason=None, llm_key=None):
        mode, key, provider = _resolve_mode(llm_key, self.settings)
        trace["mode"] = mode
        trace["provider"] = provider
        final = content
        if mode == "live" and key and handoff_reason is None and outcome in {"answered", "unknown", "refused", "hedged"}:
            final = self._phrase(final, trace, key, provider)
        if self._leaks(session, conv, final, user_text):
            final = SAFE_PII
            outcome = "refused"
            status = "resolved"
            handoff_reason = None
            trace["guardrails"].append({"rule": "pii_filter", "decision": "block", "detail": "Blocked a reply that contained another customer's data."})
        if outcome in {"unknown", "hedged"}:
            conv.offered_handoff = True
        else:
            conv.offered_handoff = False
        message = Message(id=nid("m_"), conversation_id=conv.id, role="agent", content=final, created_at=utcnow())
        session.add(message)
        session.flush()
        conv.outcome = "handoff" if handoff_reason else outcome
        conv.status = "handed_off" if handoff_reason else status
        conv.updated_at = utcnow()
        ticket_id = None
        if handoff_reason:
            ticket_id = self._ticket(session, conv, trace, handoff_reason, final)
        trace["outcome"] = conv.outcome
        session.add(TraceRecord(id=nid("tr_"), conversation_id=conv.id, message_id=message.id, body=json.dumps(trace), created_at=utcnow()))
        session.commit()
        return {
            "conversation_id": conv.id,
            "message_id": message.id,
            "reply": final,
            "mode": mode,
            "status": conv.status,
            "outcome": conv.outcome,
            "handoff": {"id": ticket_id, "reason": handoff_reason} if ticket_id else None,
            "trace": trace,
        }

    def _phrase(self, draft: str, trace: dict, key: str, provider: str) -> str:
        model = self.settings.anthropic_model if provider == "anthropic" else self.settings.openai_model
        sources = trace.get("retrieval") or []
        titles = {item["title"] for item in sources}
        titles.update(re.findall(r"\[(.+?) §", draft))
        try:
            paraphrased = phrase(draft, sources, key=key, provider=provider, model=model)
        except Exception as exc:
            trace["llm_fallback"] = safe_error(exc)
            return draft
        reason = accept_paraphrase(draft, paraphrased, titles)
        if reason:
            trace["llm_fallback"] = reason
            return draft
        trace["llm"] = "phrased"
        return paraphrased

    def _leaks(self, session, conv, reply: str, user_text: str) -> bool:
        allowed_emails = {item.lower() for item in emails(user_text)}
        if conv.customer_email:
            allowed_emails.add(conv.customer_email.lower())
        allowed_orders = set(order_numbers(user_text))
        if conv.verified_order_number:
            allowed_orders.add(conv.verified_order_number)
        if conv.verified_customer_id:
            for order in self.commerce.list_orders(session, conv.verified_customer_id):
                allowed_orders.add(order.number)
        verified_street = None
        if conv.verified_order_number:
            current = self.commerce.get_order(session, conv.verified_order_number)
            if current is not None:
                verified_street = current.line1.lower()
        lowered = reply.lower()
        for customer in session.scalars(select(Customer)).all():
            if customer.email.lower() in lowered and customer.email.lower() not in allowed_emails:
                return True
            street = (customer.line1 or "").lower()
            if street and street in lowered and street not in (user_text or "").lower():
                if not verified_street or street != verified_street:
                    return True
        for number in order_numbers(reply):
            if number not in allowed_orders:
                return True
        return False

    def _ticket(self, session, conv, trace, reason, reply) -> str:
        messages = session.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)).all()
        transcript = "\n".join(f"[{msg.created_at.isoformat()}] {msg.role}: {msg.content}" for msg in messages)
        actions = _actions(conv)
        last_customer = next((msg.content for msg in reversed(messages) if msg.role == "customer"), "")
        summary = (
            f"Customer intent: {trace.get('intent')}. Sentiment: {trace.get('sentiment')}. "
            f"Actions taken: {', '.join(actions) if actions else 'none'}. "
            f"Last customer message: {re.sub(r'\\s+', ' ', last_customer).strip()[:280]}"
        )
        requester = conv.customer_email or "chat-guest@marlowandhale.example"
        zendesk_id = None
        zendesk_state = "not_configured"
        if self.settings.zendesk_configured:
            try:
                client = ZendeskClient(self.settings.zendesk_subdomain, self.settings.zendesk_email, self.settings.zendesk_api_token)
                zendesk_id = client.create_ticket(
                    subject=f"Keel handoff ({reason})",
                    body=f"{summary}\n\nAgent reply: {reply}\n\nTranscript:\n{transcript}",
                    requester_email=requester,
                    tags=["keel", reason],
                )
                zendesk_state = "sent"
            except Exception:
                zendesk_state = "failed"
        trace["guardrails"].append({"rule": "zendesk", "decision": zendesk_state, "detail": "Local inbox ticket is always stored."})
        ticket = Ticket(
            id=nid("t_"),
            conversation_id=conv.id,
            reason=reason,
            summary=summary,
            intent=str(trace.get("intent") or reason),
            sentiment=str(trace.get("sentiment") or "calm"),
            transcript=transcript,
            actions_json=json.dumps(actions),
            zendesk_id=zendesk_id,
            status="open",
            created_at=utcnow(),
        )
        session.add(ticket)
        session.flush()
        return ticket.id

    def _record_action(self, conv, action: str) -> None:
        actions = _actions(conv)
        actions.append(action)
        conv.actions_json = json.dumps(actions)


def record_csat(session: Session, conversation_id: str, vote: str) -> Csat:
    if vote not in {"up", "down"}:
        raise ValueError("Vote must be up or down.")
    conv = session.get(Conversation, conversation_id)
    if conv is None:
        raise KeyError(conversation_id)
    row = session.scalar(select(Csat).where(Csat.conversation_id == conversation_id))
    if row is None:
        row = Csat(id=nid("cs_"), conversation_id=conversation_id, vote=vote, created_at=utcnow())
        session.add(row)
    else:
        row.vote = vote
        row.created_at = utcnow()
    session.commit()
    return row


def _actions(conv) -> list:
    try:
        data = json.loads(conv.actions_json or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _resolve_mode(header: str | None, settings: Settings) -> tuple[str, str | None, str | None]:
    key = (header or "").strip()
    provider = None
    if not key:
        if settings.anthropic_api_key:
            key = settings.anthropic_api_key
            provider = "anthropic"
        elif settings.openai_api_key:
            key = settings.openai_api_key
            provider = "openai"
    else:
        provider = "anthropic" if key.startswith("sk-ant") else "openai"
    if not key:
        return "demo", None, None
    return "live", key, provider


def _reason(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("damaged", "damage", "broken", "cracked", "dented", "chipped")):
        return "damaged"
    if "missing" in lowered:
        return "missing"
    return "customer_request"


def _amount(text: str) -> int | None:
    """The dollars tied to the refund, not the first dollar figure in the message.

    A sentence that says to ignore a review threshold still names that
    threshold. The figure next to "refund" is the request.
    """
    raw = text or ""
    matches = list(AMOUNT_RE.finditer(raw))
    if not matches:
        return None
    ignored_at: set[int] = set()
    for cue in re.finditer(r"\b(?:ignore|disregard|skip|forget)\b", raw, re.I):
        window = raw[cue.end() : cue.end() + 80]
        cut = re.search(r"\brefund", window, re.I)
        region = window[: cut.start()] if cut else window[:40]
        found = AMOUNT_RE.search(region)
        if found:
            ignored_at.add(cue.end() + found.start())
    usable = [match for match in matches if match.start() not in ignored_at]
    pool = usable or matches

    def threshold_mention(match) -> bool:
        left = raw[max(0, match.start() - 40) : match.start()].lower()
        return bool(re.search(r"\b(cap|threshold|limit|rule|review|ceiling)\b[^.]{0,40}$", left))

    asked = [match for match in pool if not threshold_mention(match)] or pool
    # Several refund figures in one message: the larger one is the request.
    # A smaller figure must not be submitted while a larger one is ignored.
    if len(asked) > 1:
        asked = sorted(asked, key=lambda match: float(match.group(1)), reverse=True)
        return int(round(float(asked[0].group(1)) * 100))
    anchors = [match.start() for match in re.finditer(r"\brefund\w*\b", raw, re.I)]
    if anchors:
        asked = sorted(asked, key=lambda match: min(abs(match.start() - anchor) for anchor in anchors))
    return int(round(float(asked[0].group(1)) * 100))


_IDENTITY_GLUE = {
    "fine", "ok", "okay", "alright", "right", "got", "correct", "sorry", "thanks",
    "thank", "you", "please", "here", "hi", "hello", "email", "mail", "order",
    "number", "postcode", "zip", "postal", "code", "address", "name", "is", "and",
    "the", "a", "an", "my", "for", "on", "it", "its", "that", "this", "yes",
    "yeah", "yep", "sure", "of", "to", "it's",
}


def _identity_only(text: str) -> bool:
    """True when the message is just the factors, with no separate question."""
    stripped = re.sub(r"\S+@\S+", " ", text or "")
    stripped = re.sub(r"mh[-\s]?\d{5}", " ", stripped, flags=re.I)
    stripped = re.sub(r"\b\d{5}(?:-\d{4})?\b", " ", stripped)
    tokens = re.findall(r"[a-z0-9']+", stripped.lower())
    return bool(tokens) and all(token in _IDENTITY_GLUE for token in tokens)


def _followup_query(session: Session, conv, text: str) -> str:
    """A short fragment keeps the previous customer question as context.

    "and dryer?" does not name a topic on its own. A full question does, and
    an earlier instruction is not context.
    """
    if len(content_tokens(text)) > 2 or order_numbers(text):
        return text
    rows = session.scalars(
        select(Message).where(Message.conversation_id == conv.id, Message.role == "customer").order_by(Message.created_at)
    ).all()
    earlier = [row.content for row in rows if row.content.strip() != (text or "").strip()]
    if not earlier or is_instructional(earlier[-1]):
        return text
    return f"{earlier[-1]} {text}"


def _address(text: str) -> dict:
    # The order number is a digit run. It must not become the street.
    scrubbed = re.sub(r"mh[-\s]?\d{5}", " ", text or "", flags=re.I)
    match = ADDR_RE.search(scrubbed)
    if not match:
        return {}
    return {
        "line1": match.group("line").strip(),
        "city": match.group("city").strip(),
        "region": match.group("region").upper(),
        "postcode": match.group("zip"),
    }


def _changes(text: str) -> dict:
    changes: dict = {}
    gift = GIFT_RE.search(text or "")
    if gift:
        changes["gift_note"] = gift.group(1).strip()
    qty = QTY_RE.search(text or "")
    if qty:
        changes["qty"] = int(qty.group(1))
    return changes


def _tool_args(intent: str, number: str, text: str) -> dict:
    args: dict = {"order_number": number}
    if intent == "update_address":
        args["address"] = _address(text)
    if intent == "edit_order":
        args["changes"] = _changes(text)
    if intent == "start_refund":
        args["amount_cents"] = _amount(text)
        args["reason"] = _reason(text)
    if intent in {"start_return", "start_refund"}:
        args["reason"] = _reason(text)
    return args


def metrics(session: Session) -> dict:
    conversations = session.scalars(select(Conversation)).all()
    closed = [row for row in conversations if row.status in {"resolved", "handed_off"}]
    hedged = [row for row in closed if row.outcome == "hedged"]
    deflected = [row for row in closed if row.status == "resolved" and row.outcome != "hedged"]
    handed = [row for row in closed if row.status == "handed_off"]
    open_rows = [row for row in conversations if row.status == "open"]
    tickets = session.scalars(select(Ticket)).all()
    reasons: dict[str, int] = {}
    for ticket in tickets:
        reasons[ticket.reason] = reasons.get(ticket.reason, 0) + 1
    votes = session.scalars(select(Csat)).all()
    up = sum(1 for vote in votes if vote.vote == "up")
    down = sum(1 for vote in votes if vote.vote == "down")
    outcomes: dict[str, int] = {}
    for row in conversations:
        outcomes[row.outcome] = outcomes.get(row.outcome, 0) + 1
    return {
        "conversations": len(conversations),
        "open": len(open_rows),
        "closed": len(closed),
        "deflected": len(deflected),
        "hedged": len(hedged),
        "handed_off": len(handed),
        "deflection_rate": (len(deflected) / len(closed)) if closed else None,
        "handoff_reasons": reasons,
        "csat_up": up,
        "csat_down": down,
        "csat_total": up + down,
        "csat_rate": (up / (up + down)) if (up + down) else None,
        "outcomes": outcomes,
        "definition": (
            "Deflection rate is resolved conversations that are not hedged, divided by resolved plus handed-off conversations. "
            "A hedged answer quotes a help-center section, says the match is uncertain, and offers a person. It is not counted as a clean deflection. "
            "Open conversations are excluded. Resolved includes direct answers, don't-know replies, and refusals. "
            "CSAT is thumbs up divided by thumbs up plus thumbs down, only where a vote was recorded. "
            "Rates are null when the denominator is zero."
        ),
    }
