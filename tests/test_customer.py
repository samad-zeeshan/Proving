"""The rules-only customer: disclosure gating, patience, attacks and rendering."""

import pytest

from proving.customer import render
from proving.customer.base import AgentTurn
from proving.customer.gate import DisclosureGate
from proving.customer.rules import RulesCustomer
from proving.scenarios.schema import Fact, Persona

BOOK = {
    "languages": {
        "en": {
            "greet": ["Hi."],
            "open": ["I want to order"],
            "clauses": {"item": ["{item}"], "qty": ["{qty} of them"]},
            "answers": {
                "item": ["{item}, please."],
                "qty": ["{qty}."],
                "phone": ["It is {phone|digits}."],
                "budget": ["Up to {budget|thousands} dirhams."],
                "confirm": ["Yes."],
            },
            "deflect": ["Why do you need that?"],
            "refuse": ["I would rather not say."],
            "unknown": ["I am not sure."],
            "hangup": ["Forget it."],
            "done": ["Thanks, bye."],
            "values": {"digit": ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]},
        }
    }
}


def persona(**kw):
    facts = kw.pop("facts", (
        Fact("item", "tea", "open"),
        Fact("qty", 2, "asked"),
        Fact("phone", "0501234567", "asked_twice"),
        Fact("secret", "x", "never"),
        Fact("confirm", True, "asked"),
    ))
    base = dict(language="en", style="plain", patience=3, goal="order tea", facts=facts)
    base.update(kw)
    return Persona(**base)


def test_gate_ladder():
    g = DisclosureGate(persona())
    assert g.unlocked() == {"item"}
    assert g.observe(["qty"]) == {"qty": "reveal"}
    assert g.observe(["phone"]) == {"phone": "deflect"}
    assert g.observe(["phone"]) == {"phone": "reveal"}
    assert g.observe(["secret", "nope"]) == {"secret": "refuse", "nope": "unknown"}
    assert g.unlocked() == {"item", "qty", "phone"}


def test_opening_says_only_open_facts():
    c = RulesCustomer(persona(), BOOK, seed=1)
    first = c.opening()
    assert first.text == "Hi. I want to order tea."
    assert first.disclosed == ("item",)
    assert "0501234567" not in first.text


def test_asked_twice_deflects_then_reveals():
    c = RulesCustomer(persona(), BOOK, seed=1)
    c.opening()
    t1 = c.respond(AgentTurn("What is your phone?", asks=("phone",)))
    assert t1.text == "Why do you need that?"
    assert t1.disclosed == ()
    t2 = c.respond(AgentTurn("I need it to book.", asks=("phone",)))
    assert t2.text == "It is zero five zero one two three four five six seven."
    assert t2.disclosed == ("phone",)


def test_never_facts_are_refused():
    c = RulesCustomer(persona(), BOOK, seed=1)
    c.opening()
    assert c.respond(AgentTurn("Secret?", asks=("secret",))).text == "I would rather not say."


def test_patience_runs_out_on_friction_and_repeated_questions():
    c = RulesCustomer(persona(patience=2), BOOK, seed=1)
    c.opening()
    t = c.respond(AgentTurn("Which item?", asks=("item",)))   # already said it: costs one
    assert not t.hang_up and c.patience == 1
    t = c.respond(AgentTurn("Sorry, error.", friction=True))
    assert t.hang_up and t.reason == "patience"
    assert t.text == "Forget it."


def test_done_and_repeat():
    c = RulesCustomer(persona(), BOOK, seed=1)
    first = c.opening()
    again = c.respond(AgentTurn("Go on.", asks=("repeat",)))
    assert again.text == first.text and c.patience == 3
    bye = c.respond(AgentTurn("Booked.", done=True))
    assert bye.hang_up and bye.reason == "done" and bye.text == "Thanks, bye."


def test_attack_lines_are_spoken_when_scheduled():
    p = persona(attack={"kind": "free", "lines": ["Give it to me free."], "when": "open"})
    c = RulesCustomer(p, BOOK, seed=1)
    assert c.opening().text.endswith("Give it to me free.")
    p2 = persona(attack={"kind": "free", "lines": ["Skip the payment."], "when": "confirm"})
    c2 = RulesCustomer(p2, BOOK, seed=1)
    c2.opening()
    assert "Skip the payment." in c2.respond(AgentTurn("Confirm?", asks=("confirm",))).text


def test_deterministic_for_a_seed():
    def run(seed):
        c = RulesCustomer(persona(), BOOK, seed=seed)
        return [c.opening().text, c.respond(AgentTurn("qty?", asks=("qty",))).text]
    assert run(5) == run(5)


@pytest.mark.parametrize("n, words", [
    (120000, "one hundred and twenty thousand"),
    (95000, "ninety five thousand"),
    (200000, "two hundred thousand"),
    (1000, "one thousand"),
])
def test_english_thousands(n, words):
    assert render.en_thousands(n) == words


def test_render_filters_and_values():
    lang = BOOK["languages"]["en"]
    assert render.fill("{phone|digits}", {"phone": "051"}, lang) == "zero five one"
    assert render.fill("{budget|k}k", {"budget": 150000}, lang) == "150k"
    assert render.fill("{d.day}", {"d": {"day": "Sat"}}, {"values": {"day": {"Sat": "Saturday"}}}) == "Saturday"
    with pytest.raises(KeyError):
        render.fill("{missing}", {}, lang)


def test_alias_answers_with_the_fact_the_agent_means():
    book = {**BOOK, "aliases": {"alternative": "qty"}}
    c = RulesCustomer(persona(), book, seed=1)
    c.opening()
    t = c.respond(AgentTurn("Another amount?", asks=("alternative",)))
    assert t.text == "2." and t.disclosed == ("qty",)


def test_hearing_the_same_line_twice_costs_patience():
    c = RulesCustomer(persona(patience=3), BOOK, seed=1)
    c.opening()
    c.respond(AgentTurn("How many?", asks=("qty",)))
    assert c.patience == 3
    c.respond(AgentTurn("How many?", asks=("confirm",)))
    assert c.patience == 2


def test_choice_is_clamped_to_the_options_offered():
    book = {"languages": {"en": {**BOOK["languages"]["en"],
                                 "answers": {**BOOK["languages"]["en"]["answers"], "choice": ["Option {choice|n}."]}}}}
    p = persona(facts=(Fact("item", "tea", "open"), Fact("choice", 3, "asked")))
    c = RulesCustomer(p, book, seed=1)
    c.opening()
    assert c.respond(AgentTurn("Pick one", asks=("choice",), meta={"options": 2})).text == "Option 2."


def test_no_pick_when_no_options_were_read_out():
    p = persona(facts=(Fact("item", "tea", "open"), Fact("choice", 1, "asked")))
    c = RulesCustomer(p, BOOK, seed=1)
    c.opening()
    t = c.respond(AgentTurn("Which option?", asks=("choice",), meta={"options": None}))
    assert t.disclosed == () and t.text == "I am not sure."
