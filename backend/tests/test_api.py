"""API smoke tests. The app seeds the shop and builds the real index."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    path = tmp_path_factory.mktemp("api")
    import os

    os.environ["KEEL_DATABASE_URL"] = f"sqlite:///{path}/keel.db"
    os.environ["KEEL_SKIP_TRAFFIC"] = "1"
    os.environ["KEEL_ANTHROPIC_API_KEY"] = ""
    os.environ["KEEL_OPENAI_API_KEY"] = ""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_health_and_widget(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["ok"] is True
    assert body["articles"] >= 30
    assert body["orders"] >= 50
    assert body["server_llm"] is False
    script = client.get("/widget/keel.js")
    assert script.status_code == 200
    assert "Marlow & Hale" in script.text
    assert "Demo mode: sample responses" in script.text


def test_chat_is_grounded_and_metrics_follow_real_rows(client):
    reply = client.post("/api/chat", json={"message": "How long do I have to return something?"})
    assert reply.status_code == 200
    body = reply.json()
    assert body["mode"] == "demo"
    assert "30 days" in body["reply"]
    assert body["handoff"] is None
    metrics = client.get("/api/metrics").json()
    assert metrics["conversations"] >= 1
    assert metrics["deflection_rate"] is None or 0 <= metrics["deflection_rate"] <= 1
    listed = client.get("/api/conversations").json()
    detail = client.get(f"/api/conversations/{body['conversation_id']}").json()
    assert any(item["id"] == body["conversation_id"] for item in listed)
    assert detail["messages"][-1]["trace"]["retrieval"]
    vote = client.post(f"/api/conversations/{body['conversation_id']}/csat", json={"vote": "up"})
    assert vote.status_code == 200
    assert client.get("/api/metrics").json()["csat_up"] >= 1


def test_pasted_key_is_not_stored(client, respx_mock):
    key = "sk-ant-api03-session-only-not-stored"
    respx_mock.post("https://api.anthropic.com/v1/messages").respond(
        json={"content": [{"type": "text", "text": "I don't have that in the Marlow & Hale help center, so I won't guess. I can connect you with a specialist if you want."}]}
    )
    response = client.post(
        "/api/chat",
        json={"message": "Do you price-match a shop I've never heard of?"},
        headers={"X-Keel-LLM-Key": key},
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "live"
    assert key not in response.text
    detail = client.get(f"/api/conversations/{response.json()['conversation_id']}").json()
    blob = str(detail)
    assert key not in blob
    # A later request without the header is demo again.
    follow = client.post("/api/chat", json={"message": "How much is ground shipping?", "conversation_id": response.json()["conversation_id"]})
    assert follow.json()["mode"] == "demo"


def test_email_webhook(client):
    response = client.post(
        "/api/channels/email",
        json={"from": "elena.voss@example.com", "subject": "Order", "text": "Where is MH-31009?"},
    )
    assert response.status_code == 200
    assert "MH-31009" in response.json()["reply"]
    assert response.json()["mode"] == "demo"
