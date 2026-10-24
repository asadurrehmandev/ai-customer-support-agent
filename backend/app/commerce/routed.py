"""Pick Shopify or Stripe when configured, otherwise the local store.

Order actions in the demo always hit the local store. A configured Shopify
shop is consulted first for reads and, when present, is the system of record
for that order number. Subscriptions consult Stripe first.
"""

from sqlalchemy.orm import Session

from app.commerce.local import LocalCommerce
from app.commerce.shopify import ShopifyAdapter
from app.commerce.stripe_api import StripeAdapter, describe
from app.commerce.types import ActionResult, OrderView, SubscriptionView
from app.config import Settings


class RoutedCommerce:
    def __init__(self, settings: Settings, shopify: ShopifyAdapter | None = None, stripe: StripeAdapter | None = None):
        self.settings = settings
        self.local = LocalCommerce(threshold_cents=settings.refund_threshold_cents)
        self.shopify = shopify
        self.stripe = stripe
        if shopify is None and settings.shopify_configured:
            self.shopify = ShopifyAdapter(settings.shopify_shop, settings.shopify_token)
        if stripe is None and settings.stripe_configured:
            self.stripe = StripeAdapter(settings.stripe_api_key)

    def get_order(self, session: Session, number: str) -> OrderView | None:
        if self.shopify is not None:
            try:
                found = self.shopify.get_order(number)
            except Exception:
                found = None
            if found is not None:
                return found
        return self.local.get_order(session, number)

    def list_orders(self, session: Session, customer_id: str) -> list[OrderView]:
        return self.local.list_orders(session, customer_id)

    def get_tracking(self, session: Session, number: str) -> ActionResult:
        return self.local.get_tracking(session, number)

    def describe_order(self, session: Session, number: str) -> ActionResult:
        return self.local.describe_order(session, number)

    def cancel_order(self, session: Session, number: str, reason: str) -> ActionResult:
        return self.local.cancel_order(session, number, reason)

    def update_address(self, session: Session, number: str, address: dict) -> ActionResult:
        return self.local.update_address(session, number, address)

    def change_order(self, session: Session, number: str, changes: dict) -> ActionResult:
        return self.local.change_order(session, number, changes)

    def start_return(self, session: Session, number: str, reason: str) -> ActionResult:
        return self.local.start_return(session, number, reason)

    def start_refund(self, session: Session, number: str, amount_cents: int | None, reason: str) -> ActionResult:
        return self.local.start_refund(session, number, amount_cents, reason)

    def get_subscription(self, session: Session, customer_id: str, email: str | None = None) -> SubscriptionView | None:
        if self.stripe is not None and email:
            try:
                found = self.stripe.get_subscription_by_email(email)
            except Exception:
                found = None
            if found is not None:
                return found
        return self.local.get_subscription(session, customer_id)

    def describe_subscription(self, session: Session, customer_id: str, email: str | None = None) -> ActionResult:
        sub = self.get_subscription(session, customer_id, email=email)
        if self.stripe is not None and email and sub is not None and sub.stripe_subscription_id:
            return ActionResult(True, "ok", describe(sub), data=sub.public(), tool="get_subscription")
        return self.local.describe_subscription(session, customer_id)

    def cancel_subscription(self, session: Session, customer_id: str) -> ActionResult:
        return self.local.cancel_subscription(session, customer_id)
