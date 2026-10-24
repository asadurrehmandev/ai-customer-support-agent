"""Marlow & Hale help center. Written as sections so the file ingester and the
in-memory seed share one corpus. Holiday cutoff is emitted as PDF. Gift cards
are emitted as HTML. Everything else is Markdown.
"""

from __future__ import annotations

ArticleSpec = dict


def articles() -> list[ArticleSpec]:
    rows: list[ArticleSpec] = [
        _md(
            "shipping-times",
            "Shipping times",
            [
                (
                    "When it leaves",
                    "Orders placed before 1pm Eastern on a business day leave our Portland, Maine workshop the same day. Later orders leave the next business day.",
                ),
                (
                    "How long it takes",
                    "Ground shipping inside the continental United States usually takes 3 to 5 business days. We ship with UPS and USPS.",
                ),
            ],
        ),
        _md(
            "shipping-costs",
            "Shipping costs",
            [
                (
                    "Ground",
                    "Ground shipping is $8, or free on orders of $75 or more before tax.",
                ),
                (
                    "Expedited",
                    "Expedited shipping is $18 and is not offered to PO boxes.",
                ),
            ],
        ),
        _md(
            "international-shipping",
            "International shipping",
            [
                (
                    "Where we ship",
                    "We currently ship to the United States and Canada. We do not ship to other countries.",
                ),
                (
                    "Duties",
                    "Canadian orders can take 7 to 12 business days, and duties may be charged on delivery. Marlow & Hale does not collect those duties in checkout.",
                ),
            ],
        ),
        _md(
            "tracking-an-order",
            "Tracking an order",
            [
                (
                    "Order states",
                    "Pending and processing orders have not shipped yet. Packed orders are in the workshop and can no longer be changed. Shipped orders are with the carrier. Delivered orders show a delivery date.",
                ),
                (
                    "Carrier scans",
                    "Shipped orders include a carrier and a tracking number. Tracking can take up to 24 hours to show a first scan.",
                ),
            ],
        ),
        _md(
            "change-address",
            "Changing the shipping address",
            [
                (
                    "Before it is packed",
                    "You can change the shipping address until the order is packed. Have the order number and the email or postcode on the order ready.",
                ),
                (
                    "After it is packed",
                    "After the order is packed, the address is locked with the carrier. We cannot redirect a UPS or USPS parcel from this chat.",
                ),
            ],
        ),
        _md(
            "cancel-order",
            "Cancelling an order",
            [
                (
                    "Window",
                    "You can cancel an order within 24 hours of placing it, and only before it has shipped. Once an order is packed or shipped, it cannot be cancelled.",
                ),
                (
                    "Final sale",
                    "Final-sale items cannot be cancelled online.",
                ),
            ],
        ),
        _md(
            "edit-order",
            "Changing an order",
            [
                (
                    "What you can change",
                    "You can change quantities or add a gift note within 24 hours of placing the order, before it is packed.",
                ),
                (
                    "What needs a person",
                    "Swapping to a different product, or changing an order that has more than one item, is done by a specialist.",
                ),
            ],
        ),
        _md(
            "returns-overview",
            "Returns",
            [
                (
                    "What can come back",
                    "Most delivered items can be returned within 30 days if they are unused and not final sale. That includes cookware, linen, and tableware.",
                ),
                (
                    "Exchanges",
                    "We do not process direct exchanges. Return the original item and place a new order.",
                ),
            ],
        ),
        _md(
            "return-window",
            "The 30-day return window",
            [
                (
                    "Window",
                    "Delivered orders can be returned within 30 days of the delivery date. The 30 days are counted from the delivery scan, not the day you placed the order.",
                ),
                (
                    "Final sale",
                    "Final-sale items, including seconds, cannot be returned.",
                ),
            ],
        ),
        _md(
            "start-a-return",
            "How to start a return",
            [
                (
                    "What we need",
                    "To start a return, give us the order number and the email or postcode on the order. Say which item is coming back.",
                ),
                (
                    "The label",
                    "Pack the item with its packing slip. The returns desk sends the label after the request is recorded. Nothing is refunded until the return is checked.",
                ),
            ],
        ),
        _md(
            "refunds",
            "Refunds",
            [
                (
                    "When",
                    "A refund on a return is available once the order shows as delivered. A refund goes back to the original payment method.",
                ),
                (
                    "Timing",
                    "After a return is checked, the refund usually appears in 5 to 7 business days. Submitting a request in chat does not move the money by itself.",
                ),
                (
                    "Review",
                    "Refund requests over $75 are reviewed by a specialist before they are submitted.",
                ),
                (
                    "Amount",
                    "We can only refund up to the amount you paid for the order.",
                ),
            ],
        ),
        _md(
            "exchanges",
            "Exchanges",
            [
                (
                    "No direct exchange",
                    "We do not process direct exchanges. Return the original item and place a new order for the replacement.",
                ),
            ],
        ),
        _md(
            "final-sale",
            "Final sale",
            [
                (
                    "Rule",
                    "Items marked final sale, including seconds and samples, cannot be returned or cancelled.",
                ),
                (
                    "Damage",
                    "A final-sale item that arrives damaged is still covered by the damaged-item policy.",
                ),
            ],
        ),
        _md(
            "damaged-items",
            "Damaged items",
            [
                (
                    "Window",
                    "If something arrives damaged, tell us within 7 days of delivery and we will refund or replace it.",
                ),
                (
                    "Photos",
                    "Photos of the damage and the packaging help the review. A specialist looks at claims on final-sale pieces.",
                ),
            ],
        ),
        _md(
            "missing-items",
            "Missing items",
            [
                (
                    "Window",
                    "If a shipped item is missing from the box, tell us within 7 days of delivery and we will send a replacement or refund that item.",
                ),
            ],
        ),
        _md(
            "warranty",
            "Cookware warranty",
            [
                (
                    "Coverage",
                    "Carbon steel and enamel cookware is warranted against manufacturing defects for 5 years.",
                ),
                (
                    "Exclusions",
                    "The warranty does not cover damage from overheating, dishwasher use, or a drop.",
                ),
            ],
        ),
        _md(
            "care-carbon-steel",
            "Caring for carbon steel",
            [
                (
                    "Washing",
                    "Wash the carbon steel pan by hand, dry it on a low burner, then wipe on a thin film of neutral oil. Do not put carbon steel in the dishwasher.",
                ),
                (
                    "Seasoning",
                    "If food starts to stick, warm the dry pan, add a few drops of oil, and wipe it out. That rebuilds the seasoning.",
                ),
            ],
        ),
        _md(
            "care-linen",
            "Caring for linen",
            [
                (
                    "Wash",
                    "Wash linen cold and hang it to dry. Skip the dryer. Heat weakens the weave.",
                ),
                (
                    "Iron",
                    "Iron linen while it is still damp if you want a smooth cloth. Wrinkles are part of the fabric.",
                ),
            ],
        ),
        _md(
            "care-enamel",
            "Caring for enamel",
            [
                (
                    "Heat",
                    "Do not heat an empty enamel pot. Thermal shock, such as a cold rinse on a hot pot, can crack the enamel.",
                ),
                (
                    "Chips",
                    "Enamel can chip if it is stacked bare or dropped. Stop cooking in a pot whose enamel is flaking into food.",
                ),
            ],
        ),
        _md(
            "pantry-subscription",
            "Hale Pantry",
            [
                (
                    "Plans",
                    "Hale Pantry is a monthly or annual shipment of pantry staples. The monthly plan is $34 and the annual plan is $348.",
                ),
                (
                    "Renewal",
                    "Monthly plans renew on the same date each month until you cancel. Annual plans are prepaid.",
                ),
            ],
        ),
        _md(
            "subscription-billing",
            "Pantry billing",
            [
                (
                    "The charge",
                    "Hale Pantry is charged to the card on file. You will see the descriptor Marlow & Hale.",
                ),
                (
                    "Lookup",
                    "You can look up the plan from this chat once you confirm an order number and the email or postcode on the account.",
                ),
            ],
        ),
        _md(
            "cancel-subscription",
            "Cancelling Hale Pantry",
            [
                (
                    "Monthly and annual",
                    "Monthly Hale Pantry plans can be cancelled before the renewal date and will not renew. Cancelling an annual plan is handled by a specialist.",
                ),
            ],
        ),
        _md(
            "pause-subscription",
            "Pausing Hale Pantry",
            [
                (
                    "Monthly only",
                    "You can pause a monthly Hale Pantry plan for one month by writing to support. Annual plans cannot be paused. This chat records the question and a specialist applies the pause.",
                ),
            ],
        ),
        _md(
            "promo-codes",
            "Promo codes",
            [
                (
                    "One code",
                    "One promo code can be used per order. Promo codes cannot be applied after an order is placed.",
                ),
            ],
        ),
        _md(
            "wholesale",
            "Wholesale",
            [
                (
                    "Trade desk",
                    "Wholesale orders start at $500 and go through wholesale@marlowandhale.example. Personal orders are prepaid.",
                ),
            ],
        ),
        _md(
            "privacy",
            "Privacy",
            [
                (
                    "What we can see",
                    "We use the email and order number you give us to find that order. A support agent can see the order tied to the details you confirm, and no other customer's orders.",
                ),
                (
                    "Lists",
                    "We do not sell customer lists.",
                ),
            ],
        ),
        _md(
            "contact",
            "Contacting support",
            [
                (
                    "Hours",
                    "Specialists are available Monday to Friday, 9am to 6pm Eastern. Write to support@marlowandhale.example or use this chat.",
                ),
            ],
        ),
        _md(
            "materials",
            "Materials",
            [
                (
                    "Metals and cloth",
                    "Our carbon steel pans are uncoated iron and carbon. Some kettle handles use a stainless fitting that contains nickel. The stoneware glaze is lead-free, and the linen is flax.",
                ),
            ],
        ),
        _md(
            "product-safety",
            "Product safety",
            [
                (
                    "Stop using it",
                    "Stop using a pan that is cracked, deeply pitted, or whose enamel is flaking into food.",
                ),
                (
                    "Injury",
                    "If a product injured someone, a specialist takes the conversation. Do not keep troubleshooting an injury in this chat.",
                ),
            ],
        ),
        _md(
            "payment-disputes",
            "Payment disputes",
            [
                (
                    "Chargebacks",
                    "If you open a chargeback with your bank, a specialist takes over and we pause the order. A delivery question can be traced from this chat without a dispute.",
                ),
            ],
        ),
        _md(
            "passwords",
            "Passwords",
            [
                (
                    "We cannot see it",
                    "We cannot see or reset your password in chat. Use the forgot-password link on the sign-in page. The link expires after a few hours.",
                ),
            ],
        ),
        {
            "id": "gift-cards",
            "title": "Gift cards",
            "kind": "html",
            "sections": [
                ("How they work", "Gift cards are sent by email and do not expire."),
                ("Limits", "Gift cards cannot be redeemed for cash. One gift card can be used on an order, and any remainder stays on the card."),
            ],
        },
        {
            "id": "holiday-cutoff",
            "title": "Holiday shipping cutoff",
            "kind": "pdf",
            "sections": [
                (
                    "Christmas",
                    "The holiday cutoff for ground shipping to the continental United States is December 16. Orders placed after December 16 may not arrive before Christmas.",
                ),
            ],
        },
    ]
    return rows


def _md(article_id: str, title: str, sections: list[tuple[str, str]]) -> ArticleSpec:
    return {"id": article_id, "title": title, "kind": "md", "sections": sections}
