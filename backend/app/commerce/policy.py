"""Policy windows. These functions are the source of truth for account actions.

Customer-facing sentences are copied from the help center so a denial cites
the same rule a person would read.
"""

from datetime import datetime, timedelta

from app.commerce.types import Decision, OrderView, SubscriptionView
from app.textutil import as_utc, money

CANCEL_WINDOW = timedelta(hours=24)
RETURN_WINDOW = timedelta(days=30)
DAMAGE_WINDOW = timedelta(days=7)
LOCKED = {"packed", "shipped", "delivered", "cancelled", "returned"}


def can_cancel(order: OrderView, now: datetime) -> Decision:
    if order.status in {"cancelled", "returned"}:
        return Decision(False, "closed", f"Order {order.number} is already {order.status}.")
    if order.status in {"packed", "shipped", "delivered"}:
        return Decision(
            False,
            "already_locked",
            "Once an order is packed or shipped, it cannot be cancelled.",
        )
    placed = as_utc(order.placed_at)
    if placed is None or as_utc(now) - placed > CANCEL_WINDOW:
        return Decision(
            False,
            "outside_window",
            "You can cancel an order within 24 hours of placing it, and only before it has shipped. This order is outside that window.",
        )
    if any(item.final_sale for item in order.items):
        return Decision(False, "final_sale", "Final-sale items cannot be cancelled online.")
    return Decision(
        True,
        "ok",
        "This order is inside the 24-hour window and it has not shipped.",
    )


def can_edit(order: OrderView, now: datetime) -> Decision:
    if order.status in LOCKED or order.status in {"cancelled", "returned"}:
        return Decision(
            False,
            "already_locked",
            "You can change quantities or add a gift note within 24 hours of placing the order, before it is packed. This order can no longer be changed.",
        )
    placed = as_utc(order.placed_at)
    if placed is None or as_utc(now) - placed > CANCEL_WINDOW:
        return Decision(
            False,
            "outside_window",
            "You can change quantities or add a gift note within 24 hours of placing the order, before it is packed. This order is outside that window.",
        )
    if any(item.final_sale for item in order.items):
        return Decision(False, "final_sale", "Final-sale items cannot be changed online.")
    return Decision(True, "ok", "This order can still be changed.")


def can_update_address(order: OrderView, now: datetime) -> Decision:
    del now
    if order.status in LOCKED or order.status in {"cancelled", "returned"}:
        return Decision(
            False,
            "address_locked",
            "After the order is packed, the address is locked with the carrier.",
        )
    return Decision(True, "ok", "You can change the shipping address until the order is packed.")


def _delivered_age(order: OrderView, now: datetime):
    if order.status != "delivered" or order.delivered_at is None:
        return None
    return as_utc(now) - as_utc(order.delivered_at)


def can_return(order: OrderView, now: datetime, *, reason: str = "customer_request") -> Decision:
    if reason in {"damaged", "missing"}:
        return can_claim_problem(order, now, reason)
    if any(item.final_sale for item in order.items):
        return Decision(
            False,
            "final_sale",
            "Final-sale items, including seconds, cannot be returned.",
        )
    age = _delivered_age(order, now)
    if age is None:
        return Decision(
            False,
            "not_delivered",
            "Delivered orders can be returned within 30 days of the delivery date. This order is not delivered yet.",
        )
    if age > RETURN_WINDOW:
        return Decision(
            False,
            "outside_window",
            "Delivered orders can be returned within 30 days of the delivery date. This one is outside that window.",
        )
    return Decision(True, "ok", "Delivered orders can be returned within 30 days of the delivery date.")


def can_claim_problem(order: OrderView, now: datetime, reason: str) -> Decision:
    age = _delivered_age(order, now)
    if reason == "damaged":
        rule = "If something arrives damaged, tell us within 7 days of delivery and we will refund or replace it."
    else:
        rule = "If a shipped item is missing from the box, tell us within 7 days of delivery and we will send a replacement or refund that item."
    if age is None:
        return Decision(False, "not_delivered", f"{rule} This order is not delivered yet.")
    if age > DAMAGE_WINDOW:
        return Decision(False, "outside_window", f"{rule} This delivery is outside that window.")
    return Decision(True, "ok", rule)


def can_refund(
    order: OrderView,
    now: datetime,
    *,
    amount_cents: int | None,
    reason: str,
    threshold_cents: int,
    prior_cents: int = 0,
) -> Decision:
    if reason in {"damaged", "missing"}:
        claim = can_claim_problem(order, now, reason)
    else:
        claim = can_return(order, now, reason="customer_request")
        if claim.ok:
            claim = Decision(
                True,
                "ok",
                "A refund on a return is available once the order shows as delivered.",
            )
    if not claim.ok:
        return claim
    amount = order.total_cents if amount_cents is None else amount_cents
    if amount <= 0:
        return Decision(False, "bad_amount", "Tell me the refund amount in dollars.")
    if prior_cents + amount > order.total_cents:
        return Decision(
            False,
            "exceeds_paid",
            f"We can only refund up to the amount you paid for the order. This order total is {money(order.total_cents)}.",
        )
    if prior_cents + amount > threshold_cents:
        return Decision(
            False,
            "threshold",
            "Refund requests over $75 are reviewed by a specialist before they are submitted. I have not submitted this one.",
            handoff_reason="refund_threshold",
        )
    return Decision(True, "ok", "The refund request is within the review limit for this chat.")


def can_cancel_subscription(sub: SubscriptionView | None) -> Decision:
    if sub is None or sub.status != "active":
        state = sub.status if sub else "missing"
        return Decision(False, "none", f"There is no active Hale Pantry plan on this account ({state}).")
    if sub.interval == "year":
        return Decision(
            False,
            "annual",
            "Cancelling an annual plan is handled by a specialist. I have not cancelled it.",
            handoff_reason="annual_plan",
        )
    return Decision(
        True,
        "ok",
        "Monthly Hale Pantry plans can be cancelled before the renewal date and will not renew.",
    )
