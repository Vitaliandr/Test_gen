import copy

import pytest
from fastapi.testclient import TestClient

from sitegen.clients.openrouter import Budget
from sitegen.core import generator, similarity
from sitegen.errors import LlmError
from tests.conftest import FakeLlm, example, make_company


def test_retold_card_is_caught():
    first = example("kapitalklar")
    retold = copy.deepcopy(first)
    retold["history"] = retold["history"].replace("компания", "фирма").replace("Компания", "Фирма")
    issues = similarity.compare(retold, "ru", [("Kapitalklar", first)])
    assert any("история" in i and "Kapitalklar" in i for i in issues)


def test_different_cards_pass():
    a, b = example("kapitalklar"), example("datenpegel")
    # языки разные, делаем вид что вторая русская
    b = dict(b, language="ru")
    assert similarity.compare(a, "ru", [("Datenpegel", b)]) == []


def test_other_language_is_skipped():
    a = example("kapitalklar")
    assert similarity.compare(a, "de", [("Kapitalklar", a)]) == []


def test_scores_are_symmetric_and_bounded():
    words, phrases = similarity.scores("Анализ отчётности эмитентов", "Отчётности эмитентов анализ")
    assert words == pytest.approx(1.0)
    assert 0 <= phrases <= 1
    assert similarity.scores("", "что угодно") == (0.0, 0.0)


def test_model_is_asked_to_rewrite_a_copy():
    class Lazy(FakeLlm):
        #сначала отдаёт копию, после замечания пишет своё
        def __call__(self, model, messages, budget, validate=None, **kw):
            prompt = messages[-1]["content"]
            self.n = 0
            with pytest.raises(ValueError, match="слишком похоже"):
                validate(self.company(prompt))
            self.feedback = True
            self.n = 5
            return validate(self.company(prompt))

    existing = [("Kapitalklar", example("kapitalklar"))]
    fake = Lazy()
    company, _ = generator.generate({"brand": "Zeta"}, "m/m", fake, Budget(1), lambda s: None, existing)
    assert fake.feedback
    assert similarity.compare(company.model_dump(), "ru", existing) == []


def test_generation_fails_if_model_keeps_copying():
    existing = [("Kapitalklar", example("kapitalklar"))]

    class Stubborn(FakeLlm):
        def company(self, prompt):
            self.n = 0
            return super().company(prompt)

    with pytest.raises((LlmError, ValueError), match="слишком похоже"):
        generator.generate({"brand": "Zeta"}, "m/m", Stubborn(), Budget(1), lambda s: None, existing)


def test_facts_cannot_be_approved_after_copying(client: TestClient):
    first = make_company(client)
    second = make_company(client)
    copied = client.get(f"/api/companies/{first}").json()["data"]
    data = client.get(f"/api/companies/{second}").json()["data"]
    for key in ("history", "specialization", "value_proposition", "faq"):
        data[key] = copied[key]
    # год и город тоже, а то упрётся в сверку фактов
    data["founding_year"] = copied["founding_year"]
    data["contacts"] = dict(copied["contacts"], email=data["contacts"]["email"])
    #реквизиты привязаны к городу, тут они мешают
    data["sections"].pop("requisites", None)
    put = client.put(f"/api/companies/{second}", json=data)
    assert put.status_code == 200, put.text
    r = client.post(f"/api/companies/{second}/approve-facts")
    assert r.status_code == 400
    assert "слишком похоже" in r.json()["detail"]


def test_team_product_and_faq_are_compared_without_names():
    first = example("kapitalklar")
    copy_ = copy.deepcopy(first)
    # имена другие, а опыт и продукт те же
    for i, person in enumerate(copy_["people"]):
        person["bio"] = person["bio"].replace(person["name"], f"Человек {i}")
        person["name"] = f"Новое Имя{i}"
    copy_["brand"], copy_["product"]["name"] = "Другой", "Другой продукт"
    for key in ("history", "specialization", "value_proposition"):
        copy_[key] = f"Совсем другой текст {key} про иную нишу и путь основателя с нуля."
    issues = similarity.compare(copy_, "ru", [("Kapitalklar", first)])
    found = " ".join(issues)
    assert "биографии команды" in found
    assert "описание продукта" in found
    assert "вопросы и ответы" in found
    assert "история" not in found
