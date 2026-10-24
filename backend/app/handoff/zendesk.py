"""Zendesk ticket client. The inbox always stores a local ticket.

When KEEL_ZENDESK_SUBDOMAIN, KEEL_ZENDESK_EMAIL, and KEEL_ZENDESK_API_TOKEN
are set, the same payload is posted to Zendesk. Tests mock that HTTP call.
"""

import httpx


class ZendeskClient:
    def __init__(self, subdomain: str, email: str, token: str, client: httpx.Client | None = None):
        self.subdomain = subdomain
        self.email = email
        self.token = token
        self.client = client or httpx.Client(timeout=20)

    def create_ticket(self, *, subject: str, body: str, requester_email: str, tags: list[str]) -> str:
        response = self.client.post(
            f"https://{self.subdomain}.zendesk.com/api/v2/tickets.json",
            json={
                "ticket": {
                    "subject": subject[:180],
                    "comment": {"body": body},
                    "requester": {"email": requester_email, "name": requester_email},
                    "tags": tags,
                }
            },
            auth=(f"{self.email}/token", self.token),
        )
        response.raise_for_status()
        return str(response.json()["ticket"]["id"])
