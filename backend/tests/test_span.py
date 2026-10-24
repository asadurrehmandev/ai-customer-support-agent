"""The quoted span follows the question's cutoff, amount, or place."""

from app.kb.span import query_branch, select_span

LEAVES = (
    "Orders placed before 1pm Eastern on a business day leave our Portland, Maine workshop the same day. "
    "Later orders leave the next business day."
)
RETURNS = (
    "Delivered orders can be returned within 30 days of the delivery date. "
    "The 30 days are counted from the delivery scan, not the day you placed the order."
)


def test_morning_cutoff_quotes_the_early_branch_only():
    span = select_span(
        "If checkout finishes before the early afternoon cutoff, does the Maine workshop send the parcel out that same business day?",
        LEAVES,
        set(),
    )
    assert span.unmet == []
    assert "1pm" in span.quote
    assert "same day" in span.quote
    assert "next business day" not in span.quote


def test_afternoon_cutoff_quotes_the_later_branch_only():
    span = select_span(
        "I submitted the checkout after the afternoon cutoff. Does that parcel wait for the following business day?",
        LEAVES,
        set(),
    )
    assert "next business day" in span.quote
    assert "1pm" not in span.quote


def test_before_1pm_is_early_even_though_1pm_is_the_cutoff():
    assert query_branch("before 1pm eastern... same day ship or no??") == "early"
    assert query_branch("at 1pm") == "late"
    assert query_branch("after 1pm") == "late"
    span = select_span("before 1pm eastern... same day ship or no??", LEAVES, set())
    assert "same day" in span.quote
    assert "next business day" not in span.quote
    assert span.unmet == []


def test_where_is_does_not_quote_a_section_that_lacks_the_object():
    wholesale = "Wholesale orders start at $500 and go through wholesale@marlowandhale.example. Personal orders are prepaid."
    span = select_span("where are the wholesale login pages for my staff", wholesale, set())
    assert span.unmet
    holiday = "The holiday cutoff for ground shipping to the continental United States is December 16."
    kept = select_span("where is the holiday shipping cutoff for christmas ground", holiday, set())
    assert kept.unmet == []
    assert "December 16" in kept.quote


def test_clock_time_selects_the_branch():
    assert query_branch("Placed at 9:30am, does the workshop send it the same day?") == "early"
    assert query_branch("Placed at 4pm, does the workshop still send it today?") == "late"
    early = select_span("Placed at 9:30am, does the workshop send it the same day?", LEAVES, set())
    late = select_span("Placed at 4pm, does the workshop still send it today?", LEAVES, set())
    assert "before 1pm" in early.quote
    assert "next business day" in late.quote
    assert "before 1pm" not in late.quote


def test_airport_hold_is_not_stated_as_policy():
    span = select_span("Is there a same-day hold for me at the airport after the workshop cutoff?", LEAVES, set())
    assert "airport" in span.unmet


def test_breakage_is_not_answered_by_the_return_window():
    span = select_span("How many days after delivery can breakage be reported?", RETURNS, set())
    assert "breakage" in span.unmet


def test_restaurant_use_is_not_settled_by_the_warranty_exclusions():
    text = "The warranty does not cover damage from overheating, dishwasher use, or a drop."
    span = select_span("Does nightly restaurant service fall under the pan warranty?", text, set())
    assert "restaurant" in span.unmet


def test_warranted_section_answers_a_warranty_question():
    text = "Carbon steel and enamel cookware is warranted against manufacturing defects for 5 years."
    span = select_span("How many years does the pan warranty last?", text, set())
    assert span.unmet == []
    assert "5 years" in span.quote


def test_hours_section_does_not_settle_saturday_phone():
    text = "Specialists are available Monday to Friday, 9am to 6pm Eastern. Write to support@marlowandhale.example or use this chat."
    span = select_span("Is someone on the phone on Saturday?", text, set())
    assert "saturday" in span.unmet
    assert "phone" in span.unmet
