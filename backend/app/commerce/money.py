"""Payment limits enforced on the tool call.

`start_refund`, `cancel_order`, and `cancel_subscription` call these helpers.
The customer message is not an input. A reason string, a claimed approval, or
an instruction cannot raise the cap, add a second payout to the same request,
or refund more than the order was paid.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MoneyClaim, ReturnRequest
from app.textutil import utcnow

ONE_ACTION_MESSAGE = "I can take one payment action for a single request. I have not taken a second one."


def prior_refund_cents(session: Session, order_number: str) -> int:
    """Every refund row on the order, from any conversation, counts."""
    amounts = session.scalars(
        select(ReturnRequest.amount_cents).where(
            ReturnRequest.order_number == order_number,
            ReturnRequest.kind == "refund",
        )
    ).all()
    return sum(amount or 0 for amount in amounts)


def claim_money_action(session: Session, request_id: str | None, tool: str) -> bool:
    """Allow one payment action for this customer message.

    A missing request id is a direct call with no message attached. Those
    calls still pass through the cap and the amount-paid check. They do not
    share a one-action slot with each other.
    """
    if not request_id:
        return True
    if session.get(MoneyClaim, request_id) is not None:
        return False
    session.add(MoneyClaim(request_id=request_id, tool=tool, created_at=utcnow()))
    session.flush()
    return True
