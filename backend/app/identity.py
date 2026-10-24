"""Identity factors.

Proof is the email or the postcode stored when the order was placed.
A ZIP that appears only because the customer is changing the ship-to address
in this same message is not proof.
"""

import re

from app.commerce.types import OrderView
from app.textutil import _DESTINATION_RE, emails, extract_postcode, normalize_postcode

_LABELED_POSTCODE = re.compile(
    r"\b(?:postcode|postal code|zip(?: code)?)\s*:?\s*(\d{5})(?:-\d{4})?\b",
    re.I,
)


def proof_email(text: str) -> str | None:
    found = emails(text)
    return found[0] if found else None


def proof_postcode(text: str) -> str | None:
    """Postcode offered as proof, after ship-to lines in this message are removed."""
    raw = re.sub(r"mh[-\s]?\d{5}", " ", text or "", flags=re.I)
    destination_zips = set()
    for match in _DESTINATION_RE.finditer(raw):
        # The address pattern ends in the ZIP. An earlier digit run is not that ZIP.
        digits = re.search(r"(\d{5})$", match.group(0))
        if digits:
            destination_zips.add(digits.group(1))
    scrubbed = _DESTINATION_RE.sub(" ", raw)

    def drop_restated(match: re.Match) -> str:
        if match.group(1) in destination_zips:
            return " "
        return match.group(0)

    scrubbed = _LABELED_POSTCODE.sub(drop_restated, scrubbed)
    return extract_postcode(scrubbed)


def stored_postcode(order: OrderView) -> str:
    """The postcode on the order when it was placed, not the current ship-to ZIP."""
    return order.identity_postcode or order.postcode or ""


def factor_match(order: OrderView | None, email: str | None, postcode: str | None) -> tuple[bool, bool]:
    if order is None:
        return False, False
    email_ok = bool(email) and order.email.lower() == email.lower()
    pc_ok = bool(postcode) and normalize_postcode(stored_postcode(order)) == normalize_postcode(postcode)
    return email_ok, pc_ok
