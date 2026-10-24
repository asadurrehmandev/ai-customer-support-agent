"""Shopify Admin REST client.

Used when KEEL_SHOPIFY_SHOP and KEEL_SHOPIFY_TOKEN are set. Tests mock the HTTP
calls. The demo store does not call Shopify.
"""

from datetime import datetime, timezone

import httpx

from app.commerce.types import ActionResult, ItemView, OrderView
from app.textutil import money


API_VERSION = "2024-10"


class ShopifyAdapter:
    def __init__(self, shop: str, token: str, client: httpx.Client | None = None):
        self.shop = shop
        self.token = token
        self.client = client or httpx.Client(timeout=20)
        self.base = f"https://{shop}.myshopify.com/admin/api/{API_VERSION}"

    def _headers(self) -> dict:
        return {"X-Shopify-Access-Token": self.token, "Content-Type": "application/json"}

    def _get_raw(self, name: str) -> dict | None:
        response = self.client.get(
            f"{self.base}/orders.json",
            params={"name": name, "status": "any"},
            headers=self._headers(),
        )
        response.raise_for_status()
        orders = response.json().get("orders") or []
        if not orders:
            # Shopify stores the name with a hash prefix.
            response = self.client.get(
                f"{self.base}/orders.json",
                params={"name": f"#{name}", "status": "any"},
                headers=self._headers(),
            )
            response.raise_for_status()
            orders = response.json().get("orders") or []
        return orders[0] if orders else None

    def get_order(self, number: str) -> OrderView | None:
        raw = self._get_raw(number)
        if raw is None:
            return None
        return _map_order(raw)

    def cancel_order(self, number: str, reason: str) -> ActionResult:
        raw = self._get_raw(number)
        if raw is None:
            return ActionResult(False, "missing", "Those details don't match an order I can access.", tool="cancel_order")
        response = self.client.post(
            f"{self.base}/orders/{raw['id']}/cancel.json",
            headers=self._headers(),
            json={"reason": "customer", "email": False, "note": reason[:200]},
        )
        response.raise_for_status()
        return ActionResult(True, "ok", f"I cancelled order {number} in Shopify.", data={"shopify_id": raw["id"]}, tool="cancel_order")

    def update_address(self, number: str, address: dict) -> ActionResult:
        raw = self._get_raw(number)
        if raw is None:
            return ActionResult(False, "missing", "Those details don't match an order I can access.", tool="update_address")
        payload = {
            "order": {
                "id": raw["id"],
                "shipping_address": {
                    "address1": address.get("line1"),
                    "city": address.get("city"),
                    "province_code": address.get("region"),
                    "zip": address.get("postcode"),
                    "country_code": "US",
                    "name": (raw.get("shipping_address") or {}).get("name") or "Customer",
                },
            }
        }
        response = self.client.put(
            f"{self.base}/orders/{raw['id']}.json",
            headers=self._headers(),
            json=payload,
        )
        response.raise_for_status()
        return ActionResult(True, "ok", f"I updated the Shopify shipping address on {number}.", tool="update_address")

    def start_refund(self, number: str, amount_cents: int, reason: str) -> ActionResult:
        raw = self._get_raw(number)
        if raw is None:
            return ActionResult(False, "missing", "Those details don't match an order I can access.", tool="start_refund")
        amount = f"{amount_cents / 100:.2f}"
        payload = {
            "refund": {
                "note": reason[:200],
                "currency": raw.get("currency") or "USD",
                "notify": False,
                "transactions": [
                    {
                        "amount": amount,
                        "kind": "refund",
                        "gateway": (raw.get("gateway") or "manual"),
                    }
                ],
            }
        }
        response = self.client.post(
            f"{self.base}/orders/{raw['id']}/refunds.json",
            headers=self._headers(),
            json=payload,
        )
        response.raise_for_status()
        return ActionResult(
            True,
            "ok",
            f"I submitted a Shopify refund for {money(amount_cents)} on {number}.",
            data=response.json(),
            tool="start_refund",
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _map_status(raw: dict) -> str:
    if raw.get("cancelled_at"):
        return "cancelled"
    fulfillment = raw.get("fulfillment_status")
    shipment = None
    fulfillments = raw.get("fulfillments") or []
    if fulfillments:
        shipment = fulfillments[0].get("shipment_status")
    if shipment == "delivered":
        return "delivered"
    if fulfillment == "fulfilled" and shipment in {None, "confirmed", "label_printed", "label_purchased"}:
        return "packed"
    if fulfillment == "fulfilled" or shipment in {"in_transit", "out_for_delivery"}:
        return "shipped"
    financial = raw.get("financial_status")
    if financial in {None, "pending"}:
        return "pending"
    return "processing"


def _map_order(raw: dict) -> OrderView:
    address = raw.get("shipping_address") or {}
    items = []
    for line in raw.get("line_items") or []:
        price = line.get("price") or "0"
        props = " ".join(str(part) for part in (line.get("properties") or [])).lower()
        items.append(
            ItemView(
                sku=str(line.get("sku") or ""),
                name=str(line.get("name") or "Item"),
                qty=int(line.get("quantity") or 1),
                unit_price_cents=int(round(float(price) * 100)),
                final_sale="final-sale" in props or "final_sale" in props,
            )
        )
    tags = (raw.get("tags") or "").lower()
    fulfillments = raw.get("fulfillments") or []
    tracking_number = fulfillments[0].get("tracking_number") if fulfillments else None
    carrier = fulfillments[0].get("tracking_company") if fulfillments else None
    name = str(raw.get("name") or "").lstrip("#")
    total = int(round(float(raw.get("total_price") or 0) * 100))
    placed = _parse_dt(raw.get("created_at")) or datetime.now(timezone.utc)
    return OrderView(
        id=str(raw.get("id")),
        number=name,
        customer_id=str((raw.get("customer") or {}).get("id") or ""),
        customer_name=((raw.get("customer") or {}).get("first_name") or "") + " " + ((raw.get("customer") or {}).get("last_name") or ""),
        email=str(raw.get("email") or ""),
        vip="vip" in tags,
        status=_map_status(raw),
        placed_at=placed,
        packed_at=None,
        shipped_at=_parse_dt(fulfillments[0].get("created_at")) if fulfillments else None,
        delivered_at=_parse_dt(fulfillments[0].get("updated_at")) if fulfillments and (fulfillments[0].get("shipment_status") == "delivered") else None,
        carrier=carrier,
        tracking_number=tracking_number,
        tracking_summary=(fulfillments[0].get("shipment_status") if fulfillments else None),
        line1=str(address.get("address1") or ""),
        city=str(address.get("city") or ""),
        region=str(address.get("province_code") or ""),
        postcode=str(address.get("zip") or ""),
        gift_note=raw.get("note"),
        total_cents=total,
        items=items,
    )
