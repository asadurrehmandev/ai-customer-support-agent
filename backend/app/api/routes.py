"""Chat, email, inbox, knowledge, and metrics."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.agent.engine import metrics, record_csat
from app.auth import COOKIE, MAX_AGE, require_console, require_webhook, require_widget_origin, sign_session
from app.db import session
from app.kb.ingest import ingest_file
from app.models import Article, Chunk, Conversation, Csat, Message, Order, Ticket, TraceRecord
from app.seed.store import DEMO_NOTES
from app.textutil import as_utc

router = APIRouter(prefix="/api")


class ChatIn(BaseModel):
    message: str
    conversation_id: str | None = None


class EmailIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_email: str = Field(alias="from")
    subject: str = ""
    text: str = ""
    message_id: str | None = None


class CsatIn(BaseModel):
    vote: str


class SearchIn(BaseModel):
    q: str


class LoginIn(BaseModel):
    password: str


def _agent(request: Request):
    return request.app.state.agent


def _db():
    return session()


def _public(result: dict) -> dict:
    return {
        "conversation_id": result["conversation_id"],
        "message_id": result["message_id"],
        "reply": result["reply"],
        "mode": result["mode"],
        "status": result["status"],
        "outcome": result["outcome"],
        "handoff": result["handoff"],
    }


@router.get("/health")
def health(request: Request):
    db = _db()
    try:
        articles = len(db.scalars(select(Article.id)).all())
        orders = len(db.scalars(select(Order.id)).all())
        conversations = len(db.scalars(select(Conversation.id)).all())
        settings = request.app.state.settings
        return {
            "ok": True,
            "service": "keel",
            "articles": articles,
            "orders": orders,
            "conversations": conversations,
            "server_llm": settings.server_llm,
            "shopify": settings.shopify_configured,
            "stripe": settings.stripe_configured,
            "zendesk": settings.zendesk_configured,
        }
    finally:
        db.close()


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    settings = request.app.state.settings
    if not hmac_equal(body.password, settings.console_password):
        raise HTTPException(401, "That password does not match.")
    response.set_cookie(
        COOKIE,
        sign_session(settings.session_secret),
        max_age=MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"ok": True}


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/session")
def auth_session(request: Request):
    require_console(request)
    return {"ok": True}


def hmac_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode(), right.encode())


@router.post("/chat")
def chat(body: ChatIn, request: Request, x_keel_llm_key: str | None = Header(default=None)):
    require_widget_origin(request)
    db = _db()
    try:
        result = _agent(request).handle(
            db,
            text=body.message,
            conversation_id=body.conversation_id,
            channel="web",
            llm_key=x_keel_llm_key,
        )
        return _public(result)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Conversation not found.") from exc
    finally:
        db.close()


@router.post("/channels/email")
async def email_in(request: Request, x_keel_llm_key: str | None = Header(default=None)):
    raw = await request.body()
    require_webhook(request.app.state.settings.email_webhook_secret, raw, request.headers.get("x-keel-signature"))
    try:
        body = EmailIn.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(400, "Email payload is not valid JSON.") from exc
    if not body.text.strip():
        raise HTTPException(400, "Email body is empty.")
    db = _db()
    try:
        result = _agent(request).handle(
            db,
            text=body.text,
            channel="email",
            email_from=body.from_email,
            email_subject=body.subject,
            llm_key=x_keel_llm_key,
        )
        return _public(result)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        db.close()


@router.get("/conversations")
def list_conversations(_: None = Depends(require_console)):
    db = _db()
    try:
        rows = db.scalars(select(Conversation).order_by(Conversation.updated_at.desc())).all()
        return [_conversation_summary(db, row) for row in rows]
    finally:
        db.close()


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, _: None = Depends(require_console)):
    db = _db()
    try:
        row = db.get(Conversation, conversation_id)
        if row is None:
            raise HTTPException(404, "Conversation not found.")
        messages = db.scalars(select(Message).where(Message.conversation_id == row.id).order_by(Message.created_at)).all()
        traces = {
            trace.message_id: json.loads(trace.body)
            for trace in db.scalars(select(TraceRecord).where(TraceRecord.conversation_id == row.id)).all()
        }
        tickets = db.scalars(select(Ticket).where(Ticket.conversation_id == row.id).order_by(Ticket.created_at)).all()
        vote = db.scalar(select(Csat).where(Csat.conversation_id == row.id))
        return {
            **_conversation_summary(db, row),
            "messages": [
                {
                    "id": msg.id,
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": _iso(msg.created_at),
                    "trace": traces.get(msg.id),
                }
                for msg in messages
            ],
            "tickets": [_ticket(ticket) for ticket in tickets],
            "csat": vote.vote if vote else None,
        }
    finally:
        db.close()


@router.post("/conversations/{conversation_id}/csat")
def csat(conversation_id: str, body: CsatIn, request: Request):
    require_widget_origin(request)
    db = _db()
    try:
        row = record_csat(db, conversation_id, body.vote)
        return {"conversation_id": conversation_id, "vote": row.vote}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Conversation not found.") from exc
    finally:
        db.close()


@router.get("/inbox")
def inbox(_: None = Depends(require_console)):
    db = _db()
    try:
        rows = db.scalars(select(Ticket).order_by(Ticket.created_at.desc())).all()
        payload = []
        for ticket in rows:
            conv = db.get(Conversation, ticket.conversation_id)
            payload.append({**_ticket(ticket), "channel": conv.channel if conv else None, "customer_name": conv.customer_name if conv else None, "customer_email": conv.customer_email if conv else None})
        return payload
    finally:
        db.close()


@router.post("/inbox/{ticket_id}/handle")
def handle_ticket(ticket_id: str, _: None = Depends(require_console)):
    db = _db()
    try:
        ticket = db.get(Ticket, ticket_id)
        if ticket is None:
            raise HTTPException(404, "Ticket not found.")
        ticket.status = "handled"
        db.commit()
        return _ticket(ticket)
    finally:
        db.close()


@router.get("/metrics")
def get_metrics(_: None = Depends(require_console)):
    db = _db()
    try:
        return metrics(db)
    finally:
        db.close()


@router.get("/kb/articles")
def list_articles(_: None = Depends(require_console)):
    db = _db()
    try:
        rows = db.scalars(select(Article).order_by(Article.title)).all()
        return [
            {"id": row.id, "title": row.title, "source_type": row.source_type, "source_name": row.source_name}
            for row in rows
        ]
    finally:
        db.close()


@router.get("/kb/articles/{article_id}")
def get_article(article_id: str, _: None = Depends(require_console)):
    db = _db()
    try:
        row = db.get(Article, article_id)
        if row is None:
            raise HTTPException(404, "Article not found.")
        chunks = db.scalars(select(Chunk).where(Chunk.article_id == article_id).order_by(Chunk.position)).all()
        return {
            "id": row.id,
            "title": row.title,
            "source_type": row.source_type,
            "source_name": row.source_name,
            "body": row.body,
            "sections": [{"section": chunk.section, "text": chunk.text} for chunk in chunks],
        }
    finally:
        db.close()


@router.post("/kb/search")
def search_kb(body: SearchIn, request: Request, _: None = Depends(require_console)):
    if not body.q.strip():
        raise HTTPException(400, "Query is empty.")
    query = request.app.state.index.prepare(body.q.strip())
    hits = request.app.state.index.search(query, k=5)
    from app.kb.relevance import best_band, hit_band, overlap_count

    return {
        "q": body.q.strip(),
        "band": best_band(query, hits) if hits else "none",
        "hits": [
            {**hit.public(), "overlap": overlap_count(query, f"{hit.title} {hit.section} {hit.text}"), "gate": hit_band(query, hit)}
            for hit in hits
        ],
    }


@router.post("/kb/documents")
async def upload_document(request: Request, file: UploadFile = File(...), _: None = Depends(require_console)):
    name = file.filename or "upload.md"
    suffix = Path(name).suffix.lower()
    if suffix not in {".md", ".markdown", ".html", ".htm", ".pdf"}:
        raise HTTPException(400, "Upload a Markdown, HTML, or PDF file.")
    data = await file.read()
    if len(data) > 2_000_000:
        raise HTTPException(400, "File is larger than 2MB.")
    from app.config import DATA_DIR

    folder = DATA_DIR / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / Path(name).name
    path.write_bytes(data)
    db = _db()
    try:
        article = ingest_file(db, path)
        db.commit()
        request.app.state.index.load_or_build(db)
        return {"id": article.id, "title": article.title, "source_type": article.source_type}
    finally:
        db.close()


@router.get("/demo/fixtures")
def fixtures():
    db = _db()
    try:
        rows = db.scalars(select(Order).order_by(Order.number)).all()
        payload = []
        for order in rows:
            if order.number not in DEMO_NOTES:
                continue
            payload.append(
                {
                    "number": order.number,
                    "email": order.email,
                    "postcode": order.postcode,
                    "status": order.status,
                    "total_cents": order.total_cents,
                    "note": DEMO_NOTES[order.number],
                }
            )
        return payload
    finally:
        db.close()


@router.get("/events")
async def events(_: None = Depends(require_console)):
    async def stream():
        import asyncio

        last = ""
        while True:
            db = _db()
            try:
                rows = db.scalars(select(Conversation.updated_at)).all()
                token = "|".join(sorted(_iso(item) or "" for item in rows))
            finally:
                db.close()
            if token != last:
                last = token
                yield f"data: {json.dumps({'conversations': len(rows)})}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(stream(), media_type="text/event-stream")


def _conversation_summary(db, row: Conversation) -> dict:
    last = db.scalar(
        select(Message).where(Message.conversation_id == row.id).order_by(Message.created_at.desc())
    )
    return {
        "id": row.id,
        "channel": row.channel,
        "status": row.status,
        "outcome": row.outcome,
        "subject": row.subject,
        "customer_name": row.customer_name,
        "customer_email": row.customer_email,
        "verified_order_number": row.verified_order_number,
        "verified_via": row.verified_via,
        "sentiment": row.sentiment,
        "last_intent": row.last_intent,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "preview": (last.content[:160] if last else ""),
    }


def _ticket(ticket: Ticket) -> dict:
    return {
        "id": ticket.id,
        "conversation_id": ticket.conversation_id,
        "reason": ticket.reason,
        "summary": ticket.summary,
        "intent": ticket.intent,
        "sentiment": ticket.sentiment,
        "actions": json.loads(ticket.actions_json or "[]"),
        "zendesk_id": ticket.zendesk_id,
        "status": ticket.status,
        "created_at": _iso(ticket.created_at),
        "transcript": ticket.transcript,
    }


def _iso(value) -> str | None:
    if value is None:
        return None
    current = as_utc(value)
    return current.isoformat() if current else None
