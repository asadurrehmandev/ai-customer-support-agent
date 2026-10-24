from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ItemView:
    sku: str
    name: str
    qty: int
    unit_price_cents: int
    final_sale: bool


@dataclass
class OrderView:
    id: str
    number: str
    customer_id: str
    customer_name: str
    email: str
    vip: bool
    status: str
    placed_at: datetime
    packed_at: datetime | None
    shipped_at: datetime | None
    delivered_at: datetime | None
    carrier: str | None
    tracking_number: str | None
    tracking_summary: str | None
    line1: str
    city: str
    region: str
    postcode: str
    gift_note: str | None
    total_cents: int
    items: list[ItemView] = field(default_factory=list)
    # Postcode the order was placed with. Shipping postcode can change later.
    identity_postcode: str = ""

    def public(self) -> dict:
        return {
            "number": self.number,
            "status": self.status,
            "email": self.email,
            "vip": self.vip,
            "total_cents": self.total_cents,
            "carrier": self.carrier,
            "tracking_number": self.tracking_number,
            "tracking_summary": self.tracking_summary,
            "line1": self.line1,
            "city": self.city,
            "region": self.region,
            "postcode": self.postcode,
            "gift_note": self.gift_note,
            "items": [item.__dict__ for item in self.items],
        }


@dataclass
class SubscriptionView:
    id: str
    customer_id: str
    plan_name: str
    interval: str
    amount_cents: int
    status: str
    renews_on: str
    stripe_subscription_id: str | None = None

    def public(self) -> dict:
        return {
            "plan_name": self.plan_name,
            "interval": self.interval,
            "amount_cents": self.amount_cents,
            "status": self.status,
            "renews_on": self.renews_on,
        }


@dataclass
class Decision:
    ok: bool
    code: str
    message: str
    handoff_reason: str | None = None


@dataclass
class ActionResult:
    ok: bool
    code: str
    message: str
    data: dict = field(default_factory=dict)
    handoff_reason: str | None = None
    tool: str = ""
