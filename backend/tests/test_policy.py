from datetime import datetime, timedelta, timezone

import pytest

from app.commerce.policy import can_cancel, can_cancel_subscription, can_refund, can_return, can_update_address
from app.commerce.types import ItemView, OrderView, SubscriptionView

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


def test_cancel_at_exact_24_hour_mark_is_still_inside():
    decision = can_cancel(order(placed_at=NOW - timedelta(hours=24)), NOW)
    assert decision.ok
    assert decision.code == "ok"


def test_cancel_one_second_after_24_hours_is_outside():
    decision = can_cancel(order(placed_at=NOW - timedelta(hours=24, seconds=1)), NOW)
    assert decision.code == "outside_window"


def test_packed_order_cannot_be_cancelled_inside_the_time_window():
    decision = can_cancel(order(status="packed", packed_at=NOW, placed_at=NOW - timedelta(minutes=20)), NOW)
    assert decision.code == "already_locked"


def test_address_can_change_while_processing():
    decision = can_update_address(order(status="processing"), NOW)
    assert decision.ok


def test_return_on_the_exact_30th_day():
    decision = can_return(order(status="delivered", delivered_at=NOW - timedelta(days=30)), NOW)
    assert decision.ok


def test_return_one_second_after_30_days():
    decision = can_return(order(status="delivered", delivered_at=NOW - timedelta(days=30, seconds=1)), NOW)
    assert decision.code == "outside_window"


def _refundable(**overrides) -> OrderView:
    return order(status="delivered", delivered_at=NOW - timedelta(days=2), total_cents=20000, **overrides)


@pytest.mark.parametrize(
    ("amount", "prior", "code", "handoff"),
    [
        (7500, 0, "ok", None),
        (7501, 0, "threshold", "refund_threshold"),
        (3500, 4000, "ok", None),
        (3501, 4000, "threshold", "refund_threshold"),
        (4000, 4000, "threshold", "refund_threshold"),
        (100, 7400, "ok", None),
        (101, 7400, "threshold", "refund_threshold"),
    ],
)
def test_refund_threshold_and_split_attempts(amount, prior, code, handoff):
    decision = can_refund(
        _refundable(),
        NOW,
        amount_cents=amount,
        reason="customer_request",
        threshold_cents=7500,
        prior_cents=prior,
    )
    assert decision.code == code
    assert decision.handoff_reason == handoff


def test_annual_plan_cancel_hands_off_and_monthly_does_not():
    annual = SubscriptionView("s", "c", "Hale Pantry", "year", 34800, "active", "2027-01-01")
    monthly = SubscriptionView("s", "c", "Hale Pantry", "month", 3400, "active", "2026-07-01")
    assert can_cancel_subscription(annual).handoff_reason == "annual_plan"
    assert can_cancel_subscription(monthly).ok


def test_damage_claim_closes_after_7_days():
    delivered = order(status="delivered", delivered_at=NOW - timedelta(days=8), total_cents=1800)
    decision = can_refund(delivered, NOW, amount_cents=1800, reason="damaged", threshold_cents=7500)
    assert not decision.ok
    assert "7 days" in decision.message
