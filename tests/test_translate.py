import pytest

from sitegen.clients.openrouter import Budget
from sitegen.core import translate
from tests.conftest import FakeLlm, example


def test_collect_takes_texts_but_not_facts():
    card = example("kapitalklar")
    keys = {"/".join(map(str, p)) for p in translate.collect(card)}
    assert "tagline" in keys
    assert "product/process/0" in keys
    assert "faq/4/answer" in keys
    assert "people/0/bio" in keys
    assert "people/0/role" in keys
    assert "product/scenarios/0/situation" in keys
    # поля разделов приходят от аспектов
    assert "sections/legal/terms/0/text" in keys
    assert "sections/security/measures/0/description" in keys
    assert "sections/references/testimonials/0/quote" in keys
    assert not [k for k in keys if k.endswith("name") or k.startswith("contacts")]
    #имена и клиенты не переводятся
    assert "brand" not in keys
    assert "sections/legal/imprint/represented_by" not in keys
    assert "sections/references/testimonials/0/author_name" not in keys
    assert "sections/references/cases/0/client" not in keys


def test_translation_keeps_facts_and_changes_language():
    card = example("kapitalklar")
    out = translate.translate_card(card, "de", "m/m", FakeLlm(), Budget(1), lambda s: None)
    assert out["language"] == "de"
    assert out["contacts"] == card["contacts"]
    assert [p["name"] for p in out["people"]] == [p["name"] for p in card["people"]]
    assert out["tagline"] == "[de] " + card["tagline"]
    assert card["language"] == "ru"
    refs, orig_refs = out["sections"]["references"], card["sections"]["references"]
    assert [c["name"] for c in refs["clients"]] == [c["name"] for c in orig_refs["clients"]]
    assert refs["testimonials"][0]["client"] == orig_refs["testimonials"][0]["client"]
    assert refs["testimonials"][0]["quote"].startswith("[de] ")
    legal, orig_legal = out["sections"]["legal"], card["sections"]["legal"]
    assert legal["imprint"]["represented_by"] == orig_legal["imprint"]["represented_by"]


def test_each_group_is_translated_by_its_own_request():
    llm = FakeLlm()
    stages: list[str] = []
    translate.translate_card(example("kapitalklar"), "de", "m/m", llm, Budget(1), stages.append)
    assert len(llm.calls) == 5
    assert len(stages) == 5
    assert any("основная карточка" in s for s in stages)
    assert any("Безопасность" in s for s in stages)


def test_translation_that_loses_numbers_is_rejected():
    card = example("kapitalklar")

    def lossy(model, messages, budget, validate=None, **kw):
        import json

        source = json.loads(messages[-1]["content"].split("\n\n", 1)[1])
        data = {k: "без цифр" for k in source}
        return validate(data)

    with pytest.raises(ValueError, match="числа|длине"):
        translate.translate_card(card, "de", "m/m", lossy, Budget(1), lambda s: None)


def test_translation_with_changed_keys_is_rejected():
    def wrong_keys(model, messages, budget, validate=None, **kw):
        return validate({"tagline": "x"})

    with pytest.raises(ValueError, match="ключей"):
        translate.translate_card(example("kapitalklar"), "de", "m/m", wrong_keys, Budget(1), lambda s: None)


def test_translation_must_keep_names():
    from sitegen.clients.openrouter import Budget
    from sitegen.core import translate
    from sitegen.errors import LlmError
    from tests.conftest import FakeLlm, example

    card = example("kapitalklar")
    brand = card["brand"]
    fake = FakeLlm()
    # модель «перевела» бренд латиницей другого вида
    fake.translation_extra = {"tagline": card["tagline"].replace(brand, brand.upper() + "X")}
    if brand not in card["tagline"]:
        fake.translation_extra = {"history": card["history"].replace(brand, "Klarkapital")}
    with pytest.raises(LlmError, match="изменилось название"):
        translate.translate_card(card, "de", "m/m", fake, Budget(1), lambda s: None)


def test_proper_names_list():
    from sitegen.core import translate
    from tests.conftest import example

    card = example("kapitalklar")
    names = translate.proper_names(card)
    assert card["brand"] in names and card["product"]["name"] in names
    assert card["people"][0]["name"] in names
    assert names == sorted(names, key=len, reverse=True)
