import re
from datetime import datetime, timezone

ORDER_RE = re.compile(r"MH[-\s]?(\d{5})", re.I)
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]+|sk-[A-Za-z0-9_\-]{8,}")

STOP = {
    "a", "an", "the", "and", "or", "to", "of", "for", "in", "on", "my", "is", "it",
    "this", "that", "with", "your", "our", "we", "you", "me", "i", "do", "does",
    "how", "what", "when", "where", "why", "can", "could", "would", "should",
    "please", "thanks", "thank", "hi", "hello", "just", "from", "have", "has",
    "was", "were", "are", "be", "if", "at", "by", "about", "into", "not",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}${cents // 100}.{cents % 100:02d}"


def normalize_order(value: str | None) -> str | None:
    if not value:
        return None
    match = ORDER_RE.search(value)
    if not match:
        return None
    return f"MH-{match.group(1)}"


def order_numbers(text: str) -> list[str]:
    found = []
    for match in ORDER_RE.finditer(text or ""):
        number = f"MH-{match.group(1)}"
        if number not in found:
            found.append(number)
    return found


def emails(text: str) -> list[str]:
    return [m.group(0) for m in EMAIL_RE.finditer(text or "")]


def normalize_postcode(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) < 5:
        return None
    return digits[:5]


# A new ship-to line is not the postcode on the account.
_DESTINATION_RE = re.compile(
    r"\b(?:to|as)\s+\d[^,\n]{2,80},\s*[^,\n]{2,40},\s*[A-Za-z]{2}\s+\d{5}\b"
)


def extract_postcode(text: str) -> str | None:
    labeled = re.search(r"\b(?:postcode|postal code|zip(?: code)?)\s*:?\s*(\d{5})\b", text or "", re.I)
    if labeled:
        return labeled.group(1)
    scrubbed = ORDER_RE.sub(" ", text or "")
    scrubbed = _DESTINATION_RE.sub(" ", scrubbed)
    scrubbed = re.sub(r"\$\s*[0-9]+(?:\.[0-9]{1,2})?", " ", scrubbed)
    match = re.search(r"\b(\d{5})(?:-\d{4})?\b", scrubbed)
    return match.group(1) if match else None


def _stem(word: str) -> str:
    if word.endswith("ing") and len(word) > 6:
        word = word[:-3]
    elif word.endswith("er") and len(word) > 4:
        word = word[:-2]
    elif word.endswith("ed") and len(word) > 5:
        word = word[:-2]
    if word.endswith("s") and len(word) >= 4 and not word.endswith("ss"):
        word = word[:-1]
    return word


def content_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    tokens = {_stem(word) for word in words if len(word) > 2 and word not in STOP}
    lowered = (text or "").lower()
    # Duration questions are looking for a day-count even when they don't say "days".
    if "how long" in lowered or "how many" in lowered:
        tokens.add("day")
    return tokens


def redact(value: str) -> str:
    return KEY_RE.sub("[redacted-key]", value)


def nid(prefix: str) -> str:
    import secrets

    return prefix + secrets.token_hex(4)
