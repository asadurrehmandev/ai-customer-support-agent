import httpx
import respx

from app.commerce.shopify import ShopifyAdapter
from app.commerce.stripe_api import StripeAdapter
from app.handoff.zendesk import ZendeskClient


SHOP = {
    "orders": [
        {
            "id": 9001,
            "name": "#MH-31003",
            "email": "theo.lang@example.com",
            "created_at": "2026-06-01T12:00:00Z",
            "financial_status": "paid",
            "fulfillment_status": "fulfilled",
            "tags": "",
            "currency": "USD",
            "total_price": "84.00",
            "gateway": "manual",
            "shipping_address": {
                "address1": "1884 Church Street",
                "city": "San Francisco",
                "province_code": "CA",
                "zip": "94110",
                "name": "Theo Lang",
            },
            "customer": {"id": 9, "first_name": "Theo", "last_name": "Lang"},
            "line_items": [{"sku": "CS-10", "name": "10-inch carbon steel frying pan", "quantity": 1, "price": "84.00"}],
            "fulfillments": [
                {
                    "tracking_number": "1Z999AA10123456784",
                    "tracking_company": "UPS",
                    "shipment_status": "in_transit",
                    "created_at": "2026-06-02T12:00:00Z",
                }
            ],
        }
    ]
}


@respx.mock
def test_shopify_reads_and_refunds():
    client = httpx.Client()
    base = "https://marlow-hale.myshopify.com/admin/api/2024-10"
    respx.get(f"{base}/orders.json").respond(json=SHOP)
    respx.post(f"{base}/orders/9001/refunds.json").respond(json={"refund": {"id": 3}})
    adapter = ShopifyAdapter("marlow-hale", "shpat_test", client=client)
    order = adapter.get_order("MH-31003")
    assert order is not None
    assert order.email == "theo.lang@example.com"
    assert order.tracking_number == "1Z999AA10123456784"
    assert order.status == "shipped"
    result = adapter.start_refund("MH-31003", 1800, "damaged")
    assert result.ok
    sent = respx.calls.last.request
    assert b"18.00" in sent.content


@respx.mock
def test_stripe_subscription_lookup():
    client = httpx.Client()
    respx.get("https://api.stripe.com/v1/customers").respond(json={"data": [{"id": "cus_demo_marcus"}]})
    respx.get("https://api.stripe.com/v1/subscriptions").respond(
        json={
            "data": [
                {
                    "id": "sub_demo_marcus",
                    "status": "active",
                    "current_period_end": 1780000000,
                    "items": {"data": [{"price": {"unit_amount": 3400, "nickname": "Hale Pantry", "recurring": {"interval": "month"}}}]},
                }
            ]
        }
    )
    adapter = StripeAdapter("sk_test_dummy", client=client)
    sub = adapter.get_subscription_by_email("marcus.adeyemi@example.com")
    assert sub is not None
    assert sub.interval == "month"
    assert sub.amount_cents == 3400
    assert sub.status == "active"


@respx.mock
def test_zendesk_create_ticket_posts_transcript():
    client = httpx.Client()
    route = respx.post("https://marlow.zendesk.com/api/v2/tickets.json").respond(json={"ticket": {"id": 77}})
    zendesk = ZendeskClient("marlow", "agent@marlowandhale.example", "token", client=client)
    ticket_id = zendesk.create_ticket(
        subject="Keel handoff",
        body="Transcript goes here",
        requester_email="elena.voss@example.com",
        tags=["keel", "angry"],
    )
    assert ticket_id == "77"
    assert route.called
    assert b"Transcript goes here" in route.calls.last.request.content
