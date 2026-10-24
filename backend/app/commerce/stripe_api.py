"""Stripe billing client for Hale Pantry subscriptions.

Used when KEEL_STRIPE_API_KEY is set. Tests mock the HTTP calls.
"""

import httpx

from app.commerce.types import ActionResult, SubscriptionView
from app.textutil import money


class StripeAdapter:
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=20)

    def _auth(self):
        return (self.api_key, "")

    def get_subscription_by_email(self, email: str) -> SubscriptionView | None:
        customers = self.client.get(
            "https://api.stripe.com/v1/customers",
            params={"email": email, "limit": 1},
            auth=self._auth(),
        )
        customers.raise_for_status()
        data = customers.json().get("data") or []
        if not data:
            return None
        customer_id = data[0]["id"]
        subs = self.client.get(
            "https://api.stripe.com/v1/subscriptions",
            params={"customer": customer_id, "status": "all", "limit": 5},
            auth=self._auth(),
        )
        subs.raise_for_status()
        rows = subs.json().get("data") or []
        if not rows:
            return None
        return _map_subscription(rows[0], customer_id)

    def cancel_at_period_end(self, subscription_id: str) -> ActionResult:
        response = self.client.post(
            f"https://api.stripe.com/v1/subscriptions/{subscription_id}",
            data={"cancel_at_period_end": "true"},
            auth=self._auth(),
        )
        response.raise_for_status()
        body = response.json()
        return ActionResult(
            True,
            "ok",
            "I set the Stripe subscription to cancel at the end of the current period.",
            data={"id": body.get("id"), "cancel_at_period_end": body.get("cancel_at_period_end")},
            tool="cancel_subscription",
        )


def _map_subscription(raw: dict, customer_id: str) -> SubscriptionView:
    item = ((raw.get("items") or {}).get("data") or [{}])[0]
    price = item.get("price") or {}
    recurring = price.get("recurring") or {}
    interval = recurring.get("interval") or "month"
    amount = int(price.get("unit_amount") or 0)
    renews = raw.get("current_period_end")
    renews_on = ""
    if isinstance(renews, int):
        from datetime import datetime, timezone

        renews_on = datetime.fromtimestamp(renews, tz=timezone.utc).date().isoformat()
    nickname = price.get("nickname") or "Hale Pantry"
    status = raw.get("status") or "active"
    if status == "active" and raw.get("cancel_at_period_end"):
        status = "cancelling"
    return SubscriptionView(
        id=str(raw.get("id")),
        customer_id=customer_id,
        plan_name=nickname,
        interval=interval,
        amount_cents=amount,
        status="active" if status == "active" else status,
        renews_on=renews_on,
        stripe_subscription_id=str(raw.get("id")),
    )


def describe(sub: SubscriptionView) -> str:
    interval = "monthly" if sub.interval == "month" else "annual"
    return (
        f"The Hale Pantry plan on this account is {interval} at {money(sub.amount_cents)}. "
        f"Status: {sub.status}. It renews on {sub.renews_on}."
    )
