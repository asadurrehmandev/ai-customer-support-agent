"""SQLite store used by the demo and by tests. The agent talks to this
through the same methods the Shopify and Stripe adapters implement.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.commerce.policy import (
    can_cancel,
    can_cancel_subscription,
    can_edit,
    can_refund,
    can_return,
    can_update_address,
)
from app.commerce.types import ActionResult, ItemView, OrderView, SubscriptionView
from app.models import Customer, Order, OrderItem, ReturnRequest, Subscription
from app.textutil import as_utc, money, nid, normalize_order, normalize_postcode


class LocalCommerce:
    def __init__(self, threshold_cents: int = 7500, clock=None):
        self.threshold_cents = threshold_cents
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def now(self) -> datetime:
        current = self.clock()
        return as_utc(current)

    def _order_row(self, session: Session, number: str) -> Order | None:
        canonical = normalize_order(number) or number
        return session.scalar(select(Order).where(Order.number == canonical))

    def _view(self, session: Session, order: Order) -> OrderView:
        items = session.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
        customer = session.get(Customer, order.customer_id)
        return OrderView(
            id=order.id,
            number=order.number,
            customer_id=order.customer_id,
            customer_name=customer.name if customer else "",
            email=order.email,
            vip=bool(customer.vip) if customer else False,
            status=order.status,
            placed_at=as_utc(order.placed_at),
            packed_at=as_utc(order.packed_at),
            shipped_at=as_utc(order.shipped_at),
            delivered_at=as_utc(order.delivered_at),
            carrier=order.carrier,
            tracking_number=order.tracking_number,
            tracking_summary=order.tracking_summary,
            line1=order.line1,
            city=order.city,
            region=order.region,
            postcode=order.postcode,
            gift_note=order.gift_note,
            total_cents=order.total_cents,
            items=[
                ItemView(i.sku, i.name, i.qty, i.unit_price_cents, i.final_sale) for i in items
            ],
        )

    def get_order(self, session: Session, number: str) -> OrderView | None:
        row = self._order_row(session, number)
        if row is None:
            return None
        return self._view(session, row)

    def list_orders(self, session: Session, customer_id: str) -> list[OrderView]:
        rows = session.scalars(select(Order).where(Order.customer_id == customer_id)).all()
        return [self._view(session, row) for row in rows]

    def get_tracking(self, session: Session, number: str) -> ActionResult:
        order = self.get_order(session, number)
        if order is None:
            return ActionResult(False, "missing", "Those details don't match an order I can access.", tool="get_tracking")
        data = {
            "number": order.number,
            "status": order.status,
            "carrier": order.carrier,
            "tracking_number": order.tracking_number,
            "tracking_summary": order.tracking_summary,
        }
        if order.tracking_number:
            message = (
                f"Order {order.number} is {order.status}. Carrier: {order.carrier}. "
                f"Tracking number: {order.tracking_number}. Latest scan: {order.tracking_summary or 'no scan text yet'}."
            )
        else:
            message = (
                f"Order {order.number} is {order.status}. Pending and processing orders have not shipped yet. "
                "Tracking can take up to 24 hours to show a first scan once it ships."
            )
        return ActionResult(True, "ok", message, data=data, tool="get_tracking")

    def describe_order(self, session: Session, number: str) -> ActionResult:
        order = self.get_order(session, number)
        if order is None:
            return ActionResult(False, "missing", "Those details don't match an order I can access.", tool="get_order")
        names = ", ".join(f"{item.qty} × {item.name}" for item in order.items) or "no line items"
        message = (
            f"Order {order.number} is {order.status}. Items: {names}. "
            f"Ship to: {order.line1}, {order.city}, {order.region} {order.postcode}. "
            f"Order total: {money(order.total_cents)}."
        )
        return ActionResult(True, "ok", message, data=order.public(), tool="get_order")

    def cancel_order(self, session: Session, number: str, reason: str) -> ActionResult:
        row = self._order_row(session, number)
        if row is None:
            return ActionResult(False, "missing", "Those details don't match an order I can access.", tool="cancel_order")
        view = self._view(session, row)
        decision = can_cancel(view, self.now())
        if not decision.ok:
            return ActionResult(False, decision.code, decision.message, tool="cancel_order")
        row.status = "cancelled"
        session.flush()
        message = (
            f"I cancelled order {view.number}. It was inside the 24-hour window and it had not shipped."
        )
        return ActionResult(True, "ok", message, data={"number": view.number, "status": "cancelled", "reason": reason}, tool="cancel_order")

    def update_address(self, session: Session, number: str, address: dict) -> ActionResult:
        row = self._order_row(session, number)
        if row is None:
            return ActionResult(False, "missing", "Those details don't match an order I can access.", tool="update_address")
        view = self._view(session, row)
        decision = can_update_address(view, self.now())
        if not decision.ok:
            return ActionResult(False, decision.code, decision.message, tool="update_address")
        required = ("line1", "city", "region", "postcode")
        if not all(address.get(key) for key in required):
            return ActionResult(
                False,
                "need_address",
                "Send the new street, city, state, and postcode, for example: 100 Court Street, Brooklyn, NY 11201.",
                tool="update_address",
            )
        row.line1 = address["line1"].strip()
        row.city = address["city"].strip()
        row.region = address["region"].strip().upper()
        row.postcode = normalize_postcode(address["postcode"]) or address["postcode"]
        session.flush()
        message = (
            f"I updated the shipping address on order {view.number} to {row.line1}, {row.city}, {row.region} {row.postcode}. "
            "You can change the shipping address until the order is packed."
        )
        return ActionResult(True, "ok", message, data={"number": view.number, "line1": row.line1, "city": row.city, "region": row.region, "postcode": row.postcode}, tool="update_address")

    def change_order(self, session: Session, number: str, changes: dict) -> ActionResult:
        row = self._order_row(session, number)
        if row is None:
            return ActionResult(False, "missing", "Those details don't match an order I can access.", tool="change_order")
        view = self._view(session, row)
        decision = can_edit(view, self.now())
        if not decision.ok:
            return ActionResult(False, decision.code, decision.message, tool="change_order")
        notes = []
        if changes.get("gift_note"):
            row.gift_note = str(changes["gift_note"]).strip()[:240]
            notes.append("gift note")
        if changes.get("qty") is not None:
            qty = int(changes["qty"])
            if qty < 1 or qty > 5:
                return ActionResult(False, "bad_qty", "I can set a quantity from 1 to 5 on this chat. For a larger change, a specialist needs to do it.", tool="change_order")
            items = session.scalars(select(OrderItem).where(OrderItem.order_id == row.id)).all()
            if len(items) != 1:
                return ActionResult(False, "multi_item", "This order has more than one item, so a specialist needs to change the quantity.", tool="change_order")
            items[0].qty = qty
            row.total_cents = items[0].unit_price_cents * qty
            notes.append(f"quantity to {qty}")
        if not notes:
            return ActionResult(
                False,
                "need_change",
                "Tell me the gift note or the new quantity. You can change quantities or add a gift note within 24 hours of placing the order, before it is packed.",
                tool="change_order",
            )
        session.flush()
        message = (
            f"I updated the {' and '.join(notes)} on order {view.number}. "
            "You can change quantities or add a gift note within 24 hours of placing the order, before it is packed."
        )
        return ActionResult(True, "ok", message, data={"number": view.number, "gift_note": row.gift_note, "total_cents": row.total_cents}, tool="change_order")

    def start_return(self, session: Session, number: str, reason: str) -> ActionResult:
        row = self._order_row(session, number)
        if row is None:
            return ActionResult(False, "missing", "Those details don't match an order I can access.", tool="start_return")
        view = self._view(session, row)
        decision = can_return(view, self.now(), reason=reason if reason in {"damaged", "missing"} else "customer_request")
        if not decision.ok:
            return ActionResult(False, decision.code, decision.message, data={"number": view.number}, tool="start_return")
        existing = session.scalar(
            select(ReturnRequest).where(ReturnRequest.order_number == view.number, ReturnRequest.kind == "return", ReturnRequest.status == "requested")
        )
        if existing is None:
            session.add(
                ReturnRequest(
                    id=nid("ret_"),
                    order_id=row.id,
                    order_number=view.number,
                    kind="return",
                    status="requested",
                    reason=reason or "customer_request",
                    amount_cents=None,
                )
            )
            session.flush()
        message = (
            f"I started a return request for order {view.number}. "
            "Delivered orders can be returned within 30 days of the delivery date. "
            "The request is recorded for the returns desk. Nothing has been refunded yet."
        )
        return ActionResult(True, "ok", message, data={"number": view.number, "kind": "return", "status": "requested"}, tool="start_return")

    def start_refund(self, session: Session, number: str, amount_cents: int | None, reason: str) -> ActionResult:
        row = self._order_row(session, number)
        if row is None:
            return ActionResult(False, "missing", "Those details don't match an order I can access.", tool="start_refund")
        view = self._view(session, row)
        decision = can_refund(
            view,
            self.now(),
            amount_cents=amount_cents,
            reason=reason,
            threshold_cents=self.threshold_cents,
        )
        if decision.handoff_reason:
            return ActionResult(
                False,
                decision.code,
                decision.message,
                data={"number": view.number, "amount_cents": amount_cents or view.total_cents},
                handoff_reason=decision.handoff_reason,
                tool="start_refund",
            )
        if not decision.ok:
            return ActionResult(False, decision.code, decision.message, data={"number": view.number}, tool="start_refund")
        amount = view.total_cents if amount_cents is None else amount_cents
        session.add(
            ReturnRequest(
                id=nid("ref_"),
                order_id=row.id,
                order_number=view.number,
                kind="refund",
                status="requested",
                reason=reason,
                amount_cents=amount,
            )
        )
        session.flush()
        message = (
            f"I submitted a refund request for {money(amount)} on order {view.number}. "
            "It is pending review and has not been paid out. "
            "A refund goes back to the original payment method after it is approved, usually in 5 to 7 business days."
        )
        return ActionResult(True, "ok", message, data={"number": view.number, "kind": "refund", "status": "requested", "amount_cents": amount}, tool="start_refund")

    def get_subscription(self, session: Session, customer_id: str) -> SubscriptionView | None:
        row = session.scalar(select(Subscription).where(Subscription.customer_id == customer_id))
        if row is None:
            return None
        return SubscriptionView(
            id=row.id,
            customer_id=row.customer_id,
            plan_name=row.plan_name,
            interval=row.interval,
            amount_cents=row.amount_cents,
            status=row.status,
            renews_on=row.renews_on,
            stripe_subscription_id=row.stripe_subscription_id,
        )

    def describe_subscription(self, session: Session, customer_id: str) -> ActionResult:
        sub = self.get_subscription(session, customer_id)
        if sub is None or sub.status != "active":
            return ActionResult(False, "none", "There is no active Hale Pantry plan on this account.", tool="get_subscription")
        interval = "monthly" if sub.interval == "month" else "annual"
        message = (
            f"The Hale Pantry plan on this account is {interval} at {money(sub.amount_cents)}. "
            f"Status: {sub.status}. It renews on {sub.renews_on}."
        )
        return ActionResult(True, "ok", message, data=sub.public(), tool="get_subscription")

    def cancel_subscription(self, session: Session, customer_id: str) -> ActionResult:
        row = session.scalar(select(Subscription).where(Subscription.customer_id == customer_id))
        view = None
        if row is not None:
            view = SubscriptionView(row.id, row.customer_id, row.plan_name, row.interval, row.amount_cents, row.status, row.renews_on, row.stripe_subscription_id)
        decision = can_cancel_subscription(view)
        if decision.handoff_reason:
            return ActionResult(False, decision.code, decision.message, handoff_reason=decision.handoff_reason, tool="cancel_subscription")
        if not decision.ok:
            return ActionResult(False, decision.code, decision.message, tool="cancel_subscription")
        row.status = "cancelled"
        session.flush()
        message = (
            f"I cancelled the monthly Hale Pantry plan so it will not renew. "
            f"The last renewal date on the plan was {row.renews_on}."
        )
        return ActionResult(True, "ok", message, data={"status": "cancelled", "renews_on": row.renews_on}, tool="cancel_subscription")
