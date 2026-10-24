"""Fictional shop: Marlow & Hale, cookware and linen, Portland, Maine.

Orders are computed from the clock at seed time so policy windows stay true
when the demo is opened later. Nothing here is a real customer.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Customer, Order, OrderItem, Product, Subscription
from app.textutil import nid

PRODUCTS = {
    "CS-10": ("10-inch carbon steel frying pan", 8400, False),
    "EN-3Q": ("3-quart enamel dutch oven", 24600, False),
    "LN-TW": ("Linen tea towels, set of 2", 3200, False),
    "WD-CB": ("Walnut cutting board", 12800, False),
    "ST-PL": ("Stoneware dinner plates, set of 4", 6400, False),
    "KT-GN": ("Gooseneck kettle", 6800, False),
    "BX-WW": ("Beeswax food wraps", 1800, False),
    "LN-SC": ("Seconds linen napkins", 1400, True),
    "KN-PR": ("Paring knife", 3600, False),
    "WD-SP": ("Birch serving spoon", 2200, False),
    "HP-MO": ("Hale Pantry monthly", 3400, False),
}

CUSTOMERS = [
    ("C1001", "Elena Voss", "elena.voss@example.com", "04101", "14 Exchange Street", "Portland", "ME", False, None),
    ("C1002", "Marcus Adeyemi", "marcus.adeyemi@example.com", "60614", "512 Dayton Street", "Chicago", "IL", False, "cus_demo_marcus"),
    ("C1003", "Priya Shah", "priya.shah@example.com", "78704", "908 West Lynn", "Austin", "TX", True, "cus_demo_priya"),
    ("C1004", "Jonah Keller", "jonah.keller@example.com", "98103", "77 Fir Street", "Seattle", "WA", False, None),
    ("C1005", "Hannah Cho", "hannah.cho@example.com", "11215", "25 Irving Place", "Brooklyn", "NY", False, None),
    ("C1006", "Owen Briggs", "owen.briggs@example.com", "80205", "640 Pearl Street", "Denver", "CO", False, None),
    ("C1007", "Sofia Marin", "sofia.marin@example.com", "97202", "9 Sycamore Row", "Portland", "OR", False, None),
    ("C1008", "Amira Hassan", "amira.hassan@example.com", "02139", "41 Putnam Avenue", "Cambridge", "MA", False, None),
    ("C1009", "Theo Lang", "theo.lang@example.com", "94110", "1884 Church Street", "San Francisco", "CA", False, None),
    ("C1010", "Chris Dalton", "chris.dalton@example.com", "80302", "15 Mapleton Avenue", "Boulder", "CO", False, None),
]

# number, customer, status, sku, timing. Timing is interpreted by status.
SPECIALS = [
    ("MH-31001", "C1007", "pending", "KT-GN", {"minutes": 20}),
    ("MH-31002", "C1005", "processing", "LN-TW", {"hours": 1}),
    ("MH-31003", "C1009", "shipped", "CS-10", {"days": 2}, "1Z999AA10123456784", "UPS", "In transit, departed Louisville KY"),
    ("MH-31004", "C1008", "delivered", "EN-3Q", {"days": 4}),
    ("MH-31005", "C1010", "delivered", "BX-WW", {"days": 2}),
    ("MH-31006", "C1004", "delivered", "KN-PR", {"edge": "inside"}),
    ("MH-31007", "C1004", "delivered", "LN-TW", {"edge": "outside"}),
    ("MH-31008", "C1001", "processing", "CS-10", {"hours": 2}),
    ("MH-31009", "C1001", "delivered", "LN-TW", {"days": 10}),
    ("MH-31010", "C1001", "packed", "WD-CB", {"hours": 3}),
    ("MH-31011", "C1006", "delivered", "LN-SC", {"days": 5}),
    ("MH-31012", "C1002", "delivered", "ST-PL", {"days": 20}),
    ("MH-31013", "C1003", "delivered", "KT-GN", {"days": 8}),
    ("MH-31014", "C1009", "delivered", "CS-10", {"days": 40}),
    ("MH-31015", "C1010", "shipped", "KN-PR", {"days": 1}),
    ("MH-31016", "C1005", "delivered", "ST-PL", {"days": 3}),
    ("MH-31017", "C1010", "delivered", "WD-SP", {"days": 2}),
    ("MH-31018", "C1001", "delivered", "WD-CB", {"days": 6}),
    ("MH-31019", "C1007", "processing", "LN-TW", {"hours": 25}),
    ("MH-31020", "C1006", "processing", "LN-SC", {"minutes": 30}),
]

DEMO_NOTES = {
    "MH-31001": "Placed minutes ago. Cancellation is still open.",
    "MH-31002": "Processing, not packed. The address can still be changed.",
    "MH-31003": "Shipped with a tracking number. Cannot be cancelled.",
    "MH-31004": "Delivered dutch oven over the $75 refund review line.",
    "MH-31005": "Delivered wraps. A damaged-item refund is inside 7 days.",
    "MH-31006": "Delivered just inside the 30-day return window.",
    "MH-31007": "Delivered just outside the 30-day return window.",
    "MH-31008": "Processing pan. A gift note can still be added.",
    "MH-31009": "Delivered towels, inside the return window.",
    "MH-31010": "Packed. Address and cancellation are locked.",
    "MH-31011": "Final-sale seconds. Not returnable unless damaged on arrival.",
    "MH-31012": "Marcus's order. Hale Pantry monthly is on this account.",
    "MH-31013": "Priya's trade account. Verifying it hands off to a person.",
    "MH-31014": "Delivered 40 days ago. The return window is closed.",
    "MH-31015": "Shipped, not delivered yet.",
    "MH-31016": "Delivered plates. A missing-item claim is inside 7 days.",
    "MH-31017": "Small delivered order, for an inflated refund amount.",
    "MH-31018": "Delivered board. A full refund is over $75.",
    "MH-31019": "Placed more than 24 hours ago and not shipped. Too late to cancel.",
    "MH-31020": "Final sale, just placed. Cannot be cancelled online.",
}


def seed_store(session: Session, now: datetime | None = None) -> None:
    moment = now or datetime.now(timezone.utc)
    by_id = {}
    for sku, (name, price, final_sale) in PRODUCTS.items():
        session.add(Product(sku=sku, name=name, price_cents=price, final_sale=final_sale))
    for row in CUSTOMERS:
        customer = Customer(
            id=row[0], name=row[1], email=row[2], postcode=row[3], line1=row[4], city=row[5], region=row[6], vip=row[7], stripe_customer_id=row[8]
        )
        session.add(customer)
        by_id[customer.id] = customer
    session.flush()
    for spec in SPECIALS:
        number, customer_id, status, sku, timing = spec[:5]
        tracking = spec[5] if len(spec) > 5 else None
        carrier = spec[6] if len(spec) > 6 else None
        summary = spec[7] if len(spec) > 7 else None
        _insert_order(session, by_id[customer_id], number, status, [(sku, 1)], timing, moment, tracking, carrier, summary)
    rng = random.Random(31000)
    filler_customers = [by_id[key] for key in ("C1001", "C1002", "C1004", "C1005", "C1006", "C1008", "C1009", "C1010", "C1007", "C1003")]
    filler_skus = ["CS-10", "LN-TW", "KT-GN", "BX-WW", "KN-PR", "ST-PL", "WD-SP"]
    for offset in range(30):
        customer = filler_customers[offset % len(filler_customers)]
        sku = filler_skus[offset % len(filler_skus)]
        status = "delivered" if offset % 5 else "shipped"
        days = rng.randint(8, 26)
        number = f"MH-{31100 + offset}"
        _insert_order(
            session,
            customer,
            number,
            status,
            [(sku, 1)],
            {"days": days},
            moment,
            tracking=f"1Z999AA3{31100 + offset}",
            carrier="USPS" if offset % 2 else "UPS",
            summary="Delivered to the front desk" if status == "delivered" else "In transit",
        )
    session.add(
        Subscription(
            id="sub_marcus",
            customer_id="C1002",
            plan_name="Hale Pantry",
            interval="month",
            amount_cents=3400,
            status="active",
            renews_on=(moment + timedelta(days=12)).date().isoformat(),
            stripe_subscription_id="sub_demo_marcus",
        )
    )
    session.add(
        Subscription(
            id="sub_priya",
            customer_id="C1003",
            plan_name="Hale Pantry",
            interval="year",
            amount_cents=34800,
            status="active",
            renews_on=(moment + timedelta(days=200)).date().isoformat(),
            stripe_subscription_id="sub_demo_priya",
        )
    )
    session.commit()


def _insert_order(session, customer, number, status, lines, timing, now, tracking=None, carrier=None, summary=None):
    placed, packed, shipped, delivered = _times(status, timing, now)
    items = []
    total = 0
    for sku, qty in lines:
        name, price, final_sale = PRODUCTS[sku]
        total += price * qty
        items.append((sku, name, qty, price, final_sale))
    if status in {"shipped", "delivered"} and tracking is None:
        tracking = f"1Z999AA2{number[-5:]}"
        carrier = carrier or "UPS"
        summary = summary or ("Delivered" if status == "delivered" else "In transit")
    order = Order(
        id=nid("ord_"),
        number=number,
        customer_id=customer.id,
        email=customer.email,
        status=status,
        placed_at=placed,
        packed_at=packed,
        shipped_at=shipped,
        delivered_at=delivered,
        carrier=carrier,
        tracking_number=tracking,
        tracking_summary=summary,
        line1=customer.line1,
        city=customer.city,
        region=customer.region,
        postcode=customer.postcode,
        gift_note=None,
        total_cents=total,
    )
    session.add(order)
    session.flush()
    for sku, name, qty, price, final_sale in items:
        session.add(
            OrderItem(
                id=nid("oi_"),
                order_id=order.id,
                sku=sku,
                name=name,
                qty=qty,
                unit_price_cents=price,
                final_sale=final_sale,
            )
        )


def _times(status: str, timing: dict, now: datetime):
    if "edge" in timing:
        if timing["edge"] == "inside":
            delivered = now - timedelta(days=30) + timedelta(minutes=5)
        else:
            delivered = now - timedelta(days=30) - timedelta(minutes=5)
        shipped = delivered - timedelta(days=3)
        placed = shipped - timedelta(days=1)
        return placed, None, shipped, delivered
    delta = timedelta(**timing)
    if status == "delivered":
        delivered = now - delta
        shipped = delivered - timedelta(days=3)
        placed = shipped - timedelta(days=1)
        return placed, None, shipped, delivered
    if status == "shipped":
        shipped = now - delta
        placed = shipped - timedelta(hours=20)
        return placed, placed + timedelta(hours=4), shipped, None
    if status == "packed":
        placed = now - delta
        return placed, now - timedelta(minutes=30), None, None
    placed = now - delta
    return placed, None, None, None
