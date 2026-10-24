"""Pick the quoted sentences inside a section from the question's constraint.

A cutoff, an amount, or a place selects the sentence that states that fact.
Quoting the single strongest sentence in the section can state the other
branch of a cutoff. If the section never mentions the constraint, the caller
quotes what the section does say and hands off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.textutil import content_tokens

_EARLY_Q = re.compile(
    r"\b(morning|before noon|before the cutoff|before \d|a\.?\s*m\.?\b|same(?: business)? day|that day|today|early)\b",
    re.I,
)
_LATE_Q = re.compile(
    r"\b(after the (?:afternoon )?cutoff|after \d|evening|tonight|following business day|next business day|too late|past the cutoff|p\.?\s*m\.?\b)\b",
    re.I,
)
_CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?\s*m\.?|p\.?\s*m\.?)\b", re.I)
_EARLY_S = re.compile(r"\bbefore\s+\d|\bsame day\b", re.I)
_LATE_S = re.compile(r"\blater orders\b|\bnext business day\b|\bnext day\b", re.I)
_HOW_MUCH = re.compile(r"\b(how many|how much|how long|cost|price|charge|fee)\b", re.I)
_NUMBER = re.compile(r"\d+")
_UNIT = re.compile(r"\b(degrees|degree|fahrenheit|celsius)\b", re.I)
_EXCLUSION = re.compile(r"other countries|do not ship to other|don't ship to other", re.I)
# A claim type is a constraint. "How many days" in the return section does not
# answer a breakage question, because that section never mentions damage.
_CLAIMS = (
    ("damage", ("damage", "damaged", "breakage", "broken", "broke", "crack", "cracked", "chip", "chipped")),
    ("missing", ("missing",)),
    ("warranty", ("warranty", "warranted", "warrantied", "warranties")),
)
# A scope word changes who or what a policy applies to. If the section never
# uses it, the section does not settle that question.
_SCOPE = ("restaurant", "commercial", "lifetime", "resale", "transferable", "industrial", "seconds")
# A channel or a day is a constraint. Hours that never mention a phone line
# do not answer "Saturday phone support".
_CHANNEL = ("phone", "telephone", "saturday", "sunday", "whatsapp", "instagram")

# Places are a constraint type, not a retrieval boost. Cities map to the region
# a shipping section would have to name.
_PLACE_REGION = {
    "canada": "canada",
    "canadian": "canada",
    "toronto": "canada",
    "vancouver": "canada",
    "montreal": "canada",
    "ottawa": "canada",
    "calgary": "canada",
    "alaska": "alaska",
    "anchorage": "alaska",
    "fairbanks": "alaska",
    "juneau": "alaska",
    "hawaii": "hawaii",
    "honolulu": "hawaii",
    "maui": "hawaii",
    "hilo": "hawaii",
    "puerto": "puerto rico",
    "guam": "guam",
    "airport": "airport",
}
_US = {"usa", "u.s", "u.s.a", "america", "american"}
_COUNTRIES = {
    "mexico", "brazil", "france", "germany", "japan", "china", "india", "italy", "spain",
    "korea", "ireland", "portugal", "sweden", "norway", "denmark", "finland", "poland",
    "greece", "turkey", "egypt", "morocco", "nigeria", "kenya", "ghana", "argentina",
    "chile", "peru", "colombia", "australia", "new zealand", "uk", "britain", "england",
    "scotland", "wales", "netherlands", "belgium", "austria", "switzerland", "thailand",
    "vietnam", "philippines", "indonesia", "malaysia", "singapore", "taiwan", "israel",
    "uae", "saudi", "qatar", "pakistan", "bangladesh", "ukraine", "romania", "hungary",
    "czech", "iceland", "luxembourg", "croatia", "serbia", "south africa", "ethiopia",
}
_DEMONYM = {
    "mexican": "mexico",
    "brazilian": "brazil",
    "french": "france",
    "german": "germany",
    "japanese": "japan",
    "chinese": "china",
    "indian": "india",
    "italian": "italy",
    "spanish": "spain",
    "korean": "korea",
    "british": "britain",
    "irish": "ireland",
    "australian": "australia",
    "nigerian": "nigeria",
}
for _name in _COUNTRIES:
    _PLACE_REGION.setdefault(_name, _name)
for _name, _region in _DEMONYM.items():
    _PLACE_REGION.setdefault(_name, _region)

_NONCONTINENTAL = {"alaska", "hawaii", "puerto rico", "guam"}
_DOMESTIC = {"canada", "united states"}


@dataclass
class Span:
    quote: str
    unmet: list[str]


def query_branch(query: str) -> str | None:
    """Early means before the stated cutoff. Late means after it."""
    text = query or ""
    clock = _CLOCK.search(text)
    if clock:
        hour = int(clock.group(1))
        minute = int(clock.group(2) or 0)
        meridiem = clock.group(3).lower().replace(" ", "").replace(".", "")
        if meridiem.startswith("p") and hour < 12:
            hour += 12
        if meridiem.startswith("a") and hour == 12:
            hour = 0
        # The shop cutoff is 1:00pm. Noon is still before it. 1:00pm is not.
        del minute
        if hour > 13 or (hour == 13 and meridiem.startswith("p")):
            return "late"
        return "early"
    late = bool(_LATE_Q.search(text))
    early = bool(_EARLY_Q.search(text))
    if late and not early:
        return "late"
    if early and not late:
        return "early"
    return None


def _sentence_branch(sentence: str) -> str | None:
    early = bool(_EARLY_S.search(sentence))
    late = bool(_LATE_S.search(sentence))
    if early and not late:
        return "early"
    if late and not early:
        return "late"
    return None


def _places(query: str) -> list[tuple[str, str]]:
    lowered = (query or "").lower()
    found: list[tuple[str, str]] = []
    if re.search(r"\bunited states\b", lowered):
        found.append(("united states", "united states"))
    for token in re.findall(r"[a-z0-9']+", lowered):
        region = _PLACE_REGION.get(token)
        if region and (token, region) not in found:
            found.append((token, region))
    if any(token in _US for token in re.findall(r"[a-z0-9.']+", lowered)):
        if ("united states", "united states") not in found:
            found.append(("united states", "united states"))
    return found


def _finish(sentences: list[str]) -> str:
    kept = []
    for sentence in sentences:
        text = sentence.strip()
        if not text:
            continue
        kept.append(text if text.endswith(".") else f"{text}.")
    return " ".join(kept)


def select_span(query: str, text: str, directory_emails: set[str] | None = None) -> Span:
    from app.agent.respond import _sentence_allowed, quotable_sentences

    emails = directory_emails or set()
    sentences = [sentence for sentence in quotable_sentences(text) if _sentence_allowed(sentence, emails)]
    if not sentences:
        return Span("", [])
    places = _places(query)
    blob = " ".join(sentences).lower()
    unmet: list[str] = []
    exclusion = False
    if places:
        for token, region in places:
            named = token in blob or region in blob or (region == "united states" and "united states" in blob)
            if named:
                continue
            if region in _NONCONTINENTAL and "continental" in blob:
                unmet.append(token)
                continue
            if region == "airport" and "airport" not in blob:
                unmet.append(token)
                continue
            if _EXCLUSION.search(blob) and region not in _DOMESTIC and region not in _NONCONTINENTAL:
                exclusion = True
                continue
            if region not in _DOMESTIC and region not in _NONCONTINENTAL:
                unmet.append(token)
    if _UNIT.search(query or "") and not _UNIT.search(blob):
        unmet.append(_UNIT.search(query).group(1).lower())
    query_tokens = set(re.findall(r"[a-z0-9']+", (query or "").lower()))
    section_tokens = set(re.findall(r"[a-z0-9']+", blob))
    for _name, words in _CLAIMS:
        asked = [word for word in words if word in query_tokens]
        if asked and not any(word in section_tokens for word in words):
            unmet.append(asked[0])
    for word in _SCOPE:
        if word in query_tokens and word not in section_tokens:
            unmet.append(word)
    for word in _CHANNEL:
        if word in query_tokens and word not in section_tokens:
            unmet.append(word)
    if exclusion and not unmet:
        chosen = [sentence for sentence in sentences if _EXCLUSION.search(sentence)] or sentences
        return Span(_finish(chosen), [])
    branch = query_branch(query)
    if branch and any(_sentence_branch(sentence) == branch for sentence in sentences):
        chosen = [sentence for sentence in sentences if _sentence_branch(sentence) == branch]
        return Span(_finish(chosen), unmet)
    numbers = set(_NUMBER.findall(query or ""))
    if numbers:
        holding = [sentence for sentence in sentences if numbers & set(_NUMBER.findall(sentence))]
        if len(holding) == 1:
            return Span(_finish(holding), unmet)
    if _HOW_MUCH.search(query or ""):
        holding = [sentence for sentence in sentences if _NUMBER.search(sentence)]
        if holding and len(holding) < len(sentences):
            return Span(_finish(holding), unmet)
    # No constraint picked a branch. Quote the section, not one stray sentence.
    return Span(_finish(sentences), unmet)


def heading_overlap(query: str, title: str, section: str) -> int:
    heading = content_tokens(f"{title} {section}")
    return len(content_tokens(query) & heading)
