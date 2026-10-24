import re
from datetime import datetime, timezone
from pathlib import Path

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

# Ordinary words a customer types. Spell correction must not rewrite these into
# a help-center term that happens to be one edit away.
COMMON = STOP | {
    "many", "days", "day", "back", "send", "time", "free", "more", "most", "than", "then",
    "come", "like", "stop", "shop", "post", "box", "leave", "today", "duty", "cost", "wash",
    "cold", "hot", "people", "work", "working", "towel", "towels", "flax", "dryer", "ground",
    "order", "orders", "plate", "morning", "pays", "goes", "much", "very", "only", "some",
    "also", "again", "here", "there", "them", "they", "those", "these", "which", "while",
    "after", "before", "over", "under", "email", "help", "need", "want", "know", "tell",
    "make", "good", "such", "been", "will", "their", "because", "through", "during",
    "without", "within", "another", "other", "same", "each", "both", "few", "own", "still",
    "even", "ever", "never", "always", "around", "something", "anything", "nothing",
    "someone", "anyone", "item", "items", "product", "products", "return", "returns",
    "shipping", "ship", "price", "paid", "pay", "card", "bank", "plan", "year", "years",
    "month", "week", "hour", "hours",     "please", "sorry", "hello", "from", "with", "your",
    "dont", "cant", "wont", "im", "pls",
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


# A new ship-to line is not the postcode on the account. The street does not
# have to be introduced with "to" or "as".
_DESTINATION_RE = re.compile(
    r"(?:\b(?:to|as)\s+)?\d[^,\n]{2,80},\s*[^,\n]{2,40},\s*[A-Za-z]{2}\s+\d{5}\b"
)


def extract_postcode(text: str) -> str | None:
    """A postcode is a standalone 5-digit ZIP or ZIP+4. A prefix or a longer run does not count."""
    labeled = re.search(
        r"\b(?:postcode|postal code|zip(?: code)?)\s*:?\s*(\d{5})(?:-(\d{4}))?\b",
        text or "",
        re.I,
    )
    if labeled:
        return labeled.group(1)
    scrubbed = ORDER_RE.sub(" ", text or "")
    scrubbed = _DESTINATION_RE.sub(" ", scrubbed)
    scrubbed = re.sub(r"\$\s*[0-9]+(?:\.[0-9]{1,2})?", " ", scrubbed)
    match = re.search(r"\b(\d{5})(?:-(\d{4}))?\b", scrubbed)
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


_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_ONES = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
_COMPOUND = re.compile(
    r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[-\s](one|two|three|four|five|six|seven|eight|nine)\b",
    re.I,
)
_BARE_TENS = re.compile(r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)\b", re.I)


def fold_numbers(text: str) -> str:
    """Write 'seventy five' as 75. Bare one/two stay words so 'two codes' is unchanged."""

    def compound(match: re.Match) -> str:
        return str(_TENS[match.group(1).lower()] + _ONES[match.group(2).lower()])

    folded = _COMPOUND.sub(compound, text or "")

    def tens(match: re.Match) -> str:
        return str(_TENS[match.group(1).lower()])

    return _BARE_TENS.sub(tens, folded)


def damerau(left: str, right: str, limit: int = 1) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    before = previous
    for i, ca in enumerate(left, 1):
        current = [i]
        smallest = i
        for j, cb in enumerate(right, 1):
            cost = 0 if ca == cb else 1
            best = min(current[j - 1] + 1, previous[j] + 1, previous[j - 1] + cost)
            if i > 1 and j > 1 and left[i - 1] == right[j - 2] and left[i - 2] == right[j - 1]:
                best = min(best, before[j - 2] + 1)
            current.append(best)
            smallest = min(smallest, best)
        if smallest > limit:
            return limit + 1
        before = previous
        previous = current
    return previous[-1]


def _english_words() -> set[str]:
    path = Path(__file__).with_name("english_10k.txt")
    if not path.exists():
        return set()
    return {line.strip().lower() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()}


_ENGLISH = _english_words()


def correct_tokens(text: str, vocab: set[str]) -> str:
    """Fix a token only when it is not an English word and the help center has one neighbor.

    Real words are left alone. This is a spell checker, not a synonym list.
    """
    protected = set()
    for local in re.findall(r"([A-Za-z0-9._+-]+)@", text or ""):
        protected.update(part.lower() for part in re.split(r"[._+-]", local) if part)

    def replace(match: re.Match) -> str:
        word = match.group(0)
        lowered = word.lower()
        if (
            lowered in vocab
            or lowered in STOP
            or lowered in COMMON
            or lowered in _ENGLISH
            or lowered in protected
            or len(lowered) < 4
            or any(character.isdigit() for character in lowered)
        ):
            return word
        found = [
            item
            for item in vocab
            if item[:1] == lowered[:1]
            and abs(len(item) - len(lowered)) <= 1
            and item not in STOP
            and damerau(lowered, item) <= 1
        ]
        if len(found) == 1:
            return found[0]
        return word

    return re.sub(r"[A-Za-z']+", replace, text or "")


def content_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    return {_stem(word) for word in words if len(word) > 2 and word not in STOP}


STREET_RE = re.compile(
    r"\b\d{1,5}\s+(?:[A-Za-z0-9.'-]+\s){0,4}(?:Street|St|Avenue|Ave|Road|Rd|Place|Pl|Row|Lane|Ln|Boulevard|Blvd)\b",
    re.I,
)


def redact(value: str) -> str:
    text = KEY_RE.sub("[redacted-key]", value or "")
    text = EMAIL_RE.sub("[redacted-email]", text)
    text = STREET_RE.sub("[redacted-street]", text)
    return text


def nid(prefix: str) -> str:
    import secrets

    return prefix + secrets.token_hex(4)
