from app.agent.read import read_message
from app.textutil import correct_tokens, fold_numbers


def test_number_words_fold_compounds_and_leave_small_counts():
    assert fold_numbers("more than seventy five") == "more than 75"
    assert fold_numbers("twenty-four hours") == "24 hours"
    assert fold_numbers("two promo codes on one order") == "two promo codes on one order"


def test_spellfix_accepts_one_neighbor_and_skips_real_words():
    vocab = {"ground", "shipping", "return", "delivery", "price", "may", "day"}
    assert correct_tokens("groud shiping", vocab) == "ground shipping"
    assert correct_tokens("retrun the pan after delivry", vocab) == "return the pan after delivery"
    assert correct_tokens("prise", vocab) == "price"
    assert correct_tokens("how many days", vocab) == "how many days"
    assert correct_tokens("spend more", vocab) == "spend more"
    assert correct_tokens("black steel", vocab) == "black steel"
    assert correct_tokens("espresso machines", vocab) == "espresso machines"
    assert correct_tokens("shipping", vocab) == "shipping"


def test_asking_about_nickel_is_not_an_injury_report():
    reading = read_message("im allergic, is there nickel in the kettle handle", verified=False, offered_handoff=False)
    assert reading.handoff_reason is None
    assert reading.intent == "kb"


def test_an_allergic_reaction_is_handed_off():
    reading = read_message("I had an allergic reaction and went to the hospital.", verified=False, offered_handoff=False)
    assert reading.handoff_reason == "safety"
