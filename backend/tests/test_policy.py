from datetime import datetime, timedelta, timezone

from app.commerce.policy import can_cancel, can_refund, can_return, can_update_address
from app.commerce.types import ItemView, OrderView

NOW = datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc)


def order(**overrides) -> OrderView:
    base = dict(
        id="ord",
        number="MH-31001",
        customer_id="C1",
        customer_name="Sofia Marin",
        email="sofia.marin@example.com",
        vip=False,
        status="processing",
        placed_at=NOW - timedelta(hours=1),
        packed_at=None,
        shipped_at=None,
        delivered_at=None,
        carrier=None,
        tracking_number=None,
        tracking_summary=None,
        line1="9 Sycamore Row",
        city="Portland",
        region="OR",
        postcode="97202",
        gift_note=None,
        total_cents=6800,
        items=[ItemView("KT-GN", "Gooseneck kettle", 1, 6800, False)],
    )
    base.update(overrides)
    return OrderView(**base)


def test_cancel_inside_window():
    decision = can_cancel(order(), NOW)
    assert decision.ok
    assert decision.code == "ok"


def test_cancel_after_24_hours():
    decision = can_cancel(order(placed_at=NOW - timedelta(hours=25)), NOW)
    assert not decision.ok
    assert decision.code == "outside_window"
    assert "24 hours" in decision.message


def test_cancel_shipped_is_locked():
    decision = can_cancel(order(status="shipped", shipped_at=NOW - timedelta(hours=2)), NOW)
    assert not decision.ok
    assert "packed or shipped" in decision.message


def test_cancel_final_sale():
    decision = can_cancel(
        order(items=[ItemView("LN-SC", "Seconds linen napkins", 1, 1400, True)]),
        NOW,
    )
    assert decision.code == "final_sale"


def test_address_locks_when_packed():
    decision = can_update_address(order(status="packed", packed_at=NOW), NOW)
    assert decision.code == "address_locked"


def test_return_on_the_30_day_boundary():
    inside = order(status="delivered", delivered_at=NOW - timedelta(days=30) + timedelta(minutes=1))
    outside = order(status="delivered", delivered_at=NOW - timedelta(days=30) - timedelta(minutes=1))
    assert can_return(inside, NOW).ok
    assert not can_return(outside, NOW).ok
    assert "30 days" in can_return(outside, NOW).message


def test_final_sale_cannot_be_returned_but_damage_can():
    item = ItemView("LN-SC", "Seconds", 1, 1400, True)
    delivered = order(status="delivered", delivered_at=NOW - timedelta(days=2), items=[item])
    assert can_return(delivered, NOW).code == "final_sale"
    damaged = can_return(delivered, NOW, reason="damaged")
    assert damaged.ok


def test_refund_over_threshold_hands_off_without_being_ok():
    delivered = order(status="delivered", delivered_at=NOW - timedelta(days=3), total_cents=24600)
    decision = can_refund(delivered, NOW, amount_cents=None, reason="customer_request", threshold_cents=7500)
    assert not decision.ok
    assert decision.handoff_reason == "refund_threshold"


def test_refund_above_amount_paid_is_a_denial():
    delivered = order(status="delivered", delivered_at=NOW - timedelta(days=2), total_cents=2200)
    decision = can_refund(delivered, NOW, amount_cents=40000, reason="customer_request", threshold_cents=7500)
    assert decision.code == "exceeds_paid"
    assert decision.handoff_reason is None


def test_small_damaged_refund_is_allowed():
    delivered = order(status="delivered", delivered_at=NOW - timedelta(days=2), total_cents=1800)
    decision = can_refund(delivered, NOW, amount_cents=1800, reason="damaged", threshold_cents=7500)
    assert decision.ok


def test_damage_claim_closes_after_7_days():
    delivered = order(status="delivered", delivered_at=NOW - timedelta(days=8), total_cents=1800)
    decision = can_refund(delivered, NOW, amount_cents=1800, reason="damaged", threshold_cents=7500)
    assert not decision.ok
    assert "7 days" in decision.message
