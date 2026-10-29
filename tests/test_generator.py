import random

import pytest

from sitegen import catalog
from sitegen.card import Contacts
from sitegen.clients.openrouter import Budget
from sitegen.core import consistency, generator
from sitegen.errors import LlmError
from tests.conftest import FakeLlm


def test_random_values_come_from_catalog():
    r = generator.resolve_params({"direction": "random", "scale": "random", "country": "DE"}, random.Random(1))
    assert r["direction"] in catalog.DIRECTIONS
    assert r["scale"] in catalog.SCALES
    assert r["city"] in catalog.COUNTRIES["DE"]["cities"]
    assert r["niche"] in catalog.NICHES


def test_exact_values_are_kept():
    req = {"brand": " Foo ", "direction": "data_analytics", "scale": "medium", "service_type": "api", "language": "de"}
    r = generator.resolve_params(req, random.Random(1))
    assert (r["brand"], r["direction"], r["scale"], r["service_type"], r["language"]) == (
        "Foo", "data_analytics", "medium", "api", "de",
    )  # fmt: skip
    lo, hi = catalog.SCALES["medium"]["employees"]
    assert lo <= r["employee_count"] <= hi


CITIES = [(country, city) for country, info in catalog.COUNTRIES.items() for city in info["cities"]]


@pytest.mark.parametrize(("country", "city"), CITIES)
def test_contacts_match_city(country: str, city: str):
    for seed in range(20):
        rng = random.Random(seed)
        r = generator.resolve_params({"country": country}, rng) | {"city": city}
        contacts = generator.make_contacts(r, "Брэнд Тест", rng)
        assert consistency.check_contacts(country, contacts, "Брэнд Тест") == []


def test_contacts_differ_between_seeds():
    r = generator.resolve_params({}, random.Random(5))
    phones = {generator.make_contacts(r, "X", random.Random(s)).phone for s in range(10)}
    assert len(phones) > 5


def test_prompt_has_brand_and_existing_companies():
    r = generator.resolve_params({"brand": "Альфа"}, random.Random(1))
    text = generator.build_prompt(r, [("Beta", {"specialization": "разбор отчётности"})])[1]["content"]
    assert "«Альфа»" in text
    assert "Beta (разбор отчётности)" in text


def test_prompt_without_brand_asks_to_invent():
    r = generator.resolve_params({}, random.Random(1))
    text = generator.build_prompt(r, [])[1]["content"]
    assert "придумай сам" in text
    assert "Уже есть такие" not in text


def test_generate_builds_valid_company():
    stages: list[str] = []
    fake = FakeLlm()
    company, params = generator.generate({"brand": "Zeta"}, "m/m", fake, Budget(1), stages.append, [])
    assert company.brand == "Zeta"
    assert consistency.check_company(company) == []
    assert params["resolved"]["city"] == company.contacts.city
    assert len(stages) == 3


def test_generate_rejects_card_with_template_leftovers():
    class Broken(FakeLlm):
        def company(self, prompt):
            card = super().company(prompt)
            card["tagline"] = "Лучшая компания {{ brand }}"
            return card

    with pytest.raises(LlmError, match="шаблонный"):
        generator.generate({}, "m/m", Broken(), Budget(1), lambda s: None, [])


def test_contacts_model_checks_postcode_format():
    with pytest.raises(ValueError):
        Contacts(city="Berlin", postal_code="101", street="a 1", phone="+49 30 1", email="a@b.de")
