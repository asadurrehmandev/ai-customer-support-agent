"""Zendesk payloads, email signatures, widget origins, and log redaction."""

import json
import logging

import httpx
import pytest
import respx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import origin_allowed, require_webhook, sign_webhook
from app.handoff.zendesk import ZendeskClient
from app.main import RedactFilter, create_app
from app.textutil import redact


@pytest.mark.parametrize(
    ("origin", "extra", "allowed"),
    [
        (None, "", True),
        ("", "", True),
        ("http://127.0.0.1:8842", "", True),
        ("http://localhost:8842", "", True),
        ("http://[::1]:8842", "", True),
        ("https://evil.example", "", False),
        ("null", "", False),
        ("https://shop.example", "https://shop.example", True),
        ("https://shop.example/", "https://shop.example", True),
        ("https://other.example", "https://shop.example, https://other.example", True),
        ("https://shop.example.evil.com", "https://shop.example", False),
        ("http://127.0.0.1.evil.com", "", False),
    ],
)
def test_widget_origin_allowlist(origin, extra, allowed):
    assert origin_allowed(origin, extra) is allowed


def test_webhook_signature_rejects_missing_bad_and_tampered_bodies():
    body = b'{"from":"elena.voss@example.com","text":"hello"}'
    signature = sign_webhook("keel-demo-email", body)
    require_webhook("keel-demo-email", body, signature)
    with pytest.raises(HTTPException) as missing:
        require_webhook("keel-demo-email", body, None)
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException):
        require_webhook("keel-demo-email", body, "sha256=" + "ab" * 32)
    with pytest.raises(HTTPException):
        require_webhook("keel-demo-email", body + b" ", signature)
    with pytest.raises(HTTPException):
        require_webhook("other-secret", body, signature)
    with pytest.raises(HTTPException) as unconfigured:
        require_webhook("", body, signature)
    assert unconfigured.value.status_code == 401


def test_redact_masks_keys_emails_and_streets():
    raw = "sk-ant-api03-session-only-not-stored wrote elena.voss@example.com at 14 Exchange Street"
    cleaned = redact(raw)
    assert "sk-ant" not in cleaned
    assert "elena.voss" not in cleaned
    assert "Exchange Street" not in cleaned
    assert "[redacted-key]" in cleaned
    assert "[redacted-email]" in cleaned
    assert "[redacted-street]" in cleaned


def test_log_filter_redacts_pii(caplog):
    filt = RedactFilter()
    record = logging.LogRecord("keel", logging.INFO, __file__, 1, "mail %s lives at %s", ("sofia.marin@example.com", "9 Sycamore Row"), None)
    assert filt.filter(record) is True
    rendered = record.getMessage()
    assert "sofia.marin" not in rendered
    assert "Sycamore" not in rendered
    caplog.set_level(logging.INFO, logger="keel-test")
    logger = logging.getLogger("keel-test")
    logger.addFilter(filt)
    logger.info("key sk-abcdefghijklmnopqrstuvwxyz")
    assert "sk-abc" not in caplog.text
    assert "[redacted-key]" in caplog.text


@respx.mock
@pytest.mark.parametrize(
    ("subject", "body", "email", "tags"),
    [
        ("Keel handoff (angry)", "Transcript:\ncustomer: this is ridiculous", "elena.voss@example.com", ["keel", "angry"]),
        ("Keel handoff (refund_threshold)", "Amount over the review line.", "amira.hassan@example.com", ["keel", "refund_threshold"]),
        ("x" * 400, "short", "guest@marlowandhale.example", ["keel", "legal"]),
    ],
)
def test_zendesk_payload_shape(subject, body, email, tags):
    route = respx.post("https://marlow.zendesk.com/api/v2/tickets.json").respond(json={"ticket": {"id": 88}})
    client = ZendeskClient("marlow", "agent@marlowandhale.example", "zd-token", client=httpx.Client())
    ticket_id = client.create_ticket(subject=subject, body=body, requester_email=email, tags=tags)
    assert ticket_id == "88"
    sent = route.calls.last.request
    payload = json.loads(sent.content)
    ticket = payload["ticket"]
    assert ticket["subject"] == subject[:180]
    assert ticket["comment"]["body"] == body
    assert ticket["requester"] == {"email": email, "name": email}
    assert ticket["tags"] == tags
    assert sent.headers["authorization"].startswith("Basic ")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os

    path = tmp_path_factory.mktemp("channels")
    os.environ["KEEL_DATABASE_URL"] = f"sqlite:///{path}/keel.db"
    os.environ["KEEL_SKIP_TRAFFIC"] = "1"
    os.environ["KEEL_ANTHROPIC_API_KEY"] = ""
    os.environ["KEEL_OPENAI_API_KEY"] = ""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_unsigned_email_is_rejected_and_a_bad_origin_cannot_chat(client):
    raw = json.dumps({"from": "elena.voss@example.com", "text": "Hello"}).encode()
    missing = client.post("/api/channels/email", content=raw, headers={"content-type": "application/json"})
    assert missing.status_code == 401
    bad = client.post(
        "/api/channels/email",
        content=raw,
        headers={"content-type": "application/json", "x-keel-signature": "sha256=" + "00" * 32},
    )
    assert bad.status_code == 401
    blocked = client.post("/api/chat", json={"message": "How much is shipping?"}, headers={"origin": "https://evil.example"})
    assert blocked.status_code == 403
    shop = client.post("/api/chat", json={"message": "How much is ground shipping?"}, headers={"origin": "http://127.0.0.1:8842"})
    assert shop.status_code == 200
    assert "$8" in shop.json()["reply"]
