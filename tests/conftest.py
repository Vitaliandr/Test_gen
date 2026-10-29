import copy
import json
import os
import random
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="sitegen_")
#до импорта приложения, settings читаются один раз
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SITES_DIR"] = f"{_tmp}/sites"
os.environ["MEDIA_DIR"] = f"{_tmp}/media"
os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"
#настоящее хранилище в тестах не трогаем
os.environ["USE_KEYRING"] = "false"
os.environ["MAX_RETRIES"] = "2"
#testserver это имя хоста у TestClient
os.environ["ALLOWED_HOSTS"] = "testserver,localhost"

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sitegen import tables  # noqa: F401
from sitegen.background import jobs
from sitegen.clients import openrouter
from sitegen.database import Base, engine
from sitegen.deps import llm_dep
from sitegen.errors import LlmError
from sitegen.main import app
from sitegen.settings import settings

# эталонные карточки для тестов, примеры для сдачи лежат отдельно в examples
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _year_nodes(obj: Any) -> list[dict[str, Any]]:
    # все словари раздела, и в списках
    found = []
    if isinstance(obj, dict):
        found.append(obj)
        for v in obj.values():
            found += _year_nodes(v)
    elif isinstance(obj, list):
        for v in obj:
            found += _year_nodes(v)
    return found


def example(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


SYLLABLES = ["ка", "ро", "ми", "ту", "ле", "на", "во", "зи", "пу", "ше", "да", "бо", "ры", "фе", "гу", "ля"]


def other_words(n: int, count: int) -> str:
    #каждой следующей компании свои слова, чтоб не было копий
    rnd = random.Random(n)
    return " ".join("".join(rnd.choice(SYLLABLES) for _ in range(3)) for _ in range(count))


RU_PRIVACY = {
    "intro": "Политика составлена в соответствии с 152-ФЗ «О персональных данных» и описывает, какие данные "
             "обрабатываются при посещении сайта и обращении к компании.",
    "controller_note": "Оператором персональных данных является ООО «Капиталклар Аналитика».",
    "data_processed": [
        {"category": "Серверные журналы", "purpose": "Работа и безопасность сайта: IP-адрес, время запроса и страница.",
         "legal_basis": "законный интерес оператора, статья 6 152-ФЗ",
         "actions": "сбор, запись, хранение, уничтожение", "retention": "до 14 дней"},
        {"category": "Переписка по почте и телефону", "purpose": "Ответы на запросы, которые человек присылает сам.",
         "legal_basis": "согласие субъекта, выраженное отправкой письма, статья 6 152-ФЗ",
         "actions": "сбор, запись, систематизация, хранение, уничтожение", "retention": "до достижения цели"},
    ],
    "recipients": ["Хостинг-провайдер, который обрабатывает данные по поручению оператора"],
    "rights": [
        "Получить сведения об обработке своих персональных данных",
        "Требовать уточнения, блокирования или уничтожения данных",
        "Отозвать согласие на обработку",
        "Обжаловать действия оператора в Роскомнадзоре или в суде",
    ],
    "cookies_statement": "Сайт не использует cookie, счётчики посещений и инструменты веб-аналитики.",
    "contact_for_requests": "Запросы о персональных данных направляйте по почте, "
                            "ответ придёт в течение 10 рабочих дней.",
    "sections": [
        {"title": "Принципы обработки персональных данных",
         "text": "Обработка ведётся законно и справедливо, только для заранее определённых целей "
                 "и в объёме, который им нужен."},
        {"title": "Условия обработки персональных данных",
         "text": "Оператор обрабатывает данные при наличии согласия субъекта или иного основания, "
                 "предусмотренного законом."},
        {"title": "Порядок сбора, хранения, передачи и уничтожения",
         "text": "Запись, систематизация и хранение данных граждан РФ ведутся с использованием баз данных "
                 "на территории Российской Федерации, по достижении цели данные уничтожаются."},
        {"title": "Трансграничная передача персональных данных",
         "text": "Оператор не передаёт персональные данные на территорию иностранных государств и иностранным лицам."},
        {"title": "Конфиденциальность персональных данных",
         "text": "Оператор и иные лица, получившие доступ к персональным данным, "
                 "не раскрывают их без согласия субъекта."},
        {"title": "Заключительные положения",
         "text": "Политика действует бессрочно до замены новой версией и постоянно доступна на этой странице сайта."},
    ],
    "effective_year": 2026,
}


def ru_card() -> dict[str, Any]:
    # kapitalklar в Москве, с российскими правилами
    text = json.dumps(example("kapitalklar"), ensure_ascii=False)
    text = text.replace("Kapitalklar Analytics GmbH", "ООО «Капиталклар Аналитика»").replace("в Берлине", "в Москве")
    text = text.replace("Федеративной Республики Германия", "Российской Федерации")
    data: dict[str, Any] = json.loads(text)
    data["country"] = "RU"
    data["contacts"] = {"city": "Москва", "postal_code": "101000", "street": "ул. Ленина, д. 12",
                        "phone": "+7 495 123 4567", "email": "info@kapitalklar.ru"}
    data["sections"]["privacy"] = copy.deepcopy(RU_PRIVACY)
    #реквизиты собираем тем же кодом, что в приложении
    from sitegen.aspects import registry
    from sitegen.aspects.base import Ctx

    data["sections"]["requisites"] = registry.get("requisites").build(Ctx.from_card(data))
    return data


class FakeLlm:
    #вместо openrouter, готовая карточка или "перевод"
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []
        self.error: Exception | None = None
        self.n = 0
        # готовые разделы для аспектов, которых нет в примерах
        self.custom: dict[str, dict[str, Any]] = {}
        # ответ проверки и что ей прислали
        self.contradictions: list[dict[str, str]] = []
        self.reviews: list[str] = []
        #подмена перевода, ключ sections/legal/terms/0/text
        self.translation_extra: dict[str, str] = {}

    def __call__(self, model: str, messages: list[dict[str, str]], budget: Any, validate: Any = None, **kw: Any) -> Any:
        self.calls.append(messages)
        if self.error:
            raise self.error
        budget.check()
        budget.add(0.003)
        prompt = messages[-1]["content"]
        if "переводчик" in messages[0]["content"]:
            source = json.loads(prompt.split("\n\n", 1)[1])
            data = {k: self.translation_extra.get(k, "[de] " + v) for k, v in source.items()}
        elif messages[0]["content"].startswith("Ты проверяющий"):
            self.reviews.append(prompt)
            data = {"contradictions": copy.deepcopy(self.contradictions)}
        elif prompt.startswith("РАЗДЕЛ: "):
            data = self.section(prompt)
        else:
            data = self.company(prompt)
        if validate is None:
            return data
        try:
            return validate(data)
        except ValueError as e:
            # как настоящий клиент после всех повторов
            raise LlmError(f"Модель не дала корректный ответ. Последняя ошибка: {e}") from None

    def section(self, prompt: str) -> dict[str, Any]:
        key = prompt.split("\n", 1)[0].removeprefix("РАЗДЕЛ: ")
        if key in self.custom:
            return copy.deepcopy(self.custom[key])
        facts = re.search(r"бренд: (.+?), юридическое название: (.+?), основана в (\d+)", prompt)
        assert facts
        text = json.dumps(example("kapitalklar")["sections"][key], ensure_ascii=False)
        text = text.replace("Kapitalklar Analytics GmbH", facts.group(2)).replace("Kapitalklar", facts.group(1))
        data: dict[str, Any] = json.loads(text)
        # годы подгоняем под год основания случайной компании
        for node in _year_nodes(data):
            for field in ("since_year", "year", "effective_year"):
                if field in node:
                    node[field] = datetime.now().year
        return data

    def company(self, prompt: str) -> dict[str, Any]:
        self.n += 1
        card = example("kapitalklar")
        for key in ("country", "direction", "service_type", "scale", "language", "contacts", "sections"):
            card.pop(key)
        m = re.search(r"Название бренда: «(.+?)»", prompt)
        brand = m.group(1) if m else f"Testbrand{self.n}"
        form = re.search(r"Организационно-правовая форма: (.+?)\.\n", prompt)
        year = re.search(r"Год основания: (\d+)", prompt)
        assert form and year
        card["brand"] = brand
        card["legal_name"] = f"{brand} {form.group(1)}"
        card["founding_year"] = int(year.group(1))
        card["history"] = card["history"].replace("2022", year.group(1))
        # город из запроса, не из примера
        city = re.search(r"город: (.+?)\.\n", prompt)
        assert city
        card["history"] = card["history"].replace("в Берлине", f"в городе {city.group(1)}")
        if self.n > 1:
            #вторая компания не должна быть копией первой
            founded, place = year.group(1), city.group(1)
            card["history"] = f"Компания основана в {founded} году в городе {place}. {other_words(self.n, 40)}."
            card["specialization"] = f"Специализация: {other_words(self.n * 7, 25)}."
            card["value_proposition"] = f"Предложение: {other_words(self.n * 13, 25)}."
            for i, person in enumerate(card["people"]):
                person["bio"] = f"Опыт: {other_words(self.n * 17 + i, 14)}."
            product = card["product"]
            product["summary"] = f"Продукт: {other_words(self.n * 19, 14)}."
            for key in ("inputs", "process", "outputs", "limitations"):
                product[key] = [other_words(self.n * 23 + i + len(key), 6) for i in range(len(product[key]))]
            for i, qa in enumerate(card["faq"]):
                qa["question"] = f"Вопрос {other_words(self.n * 29 + i, 4)}?"
                qa["answer"] = f"Ответ: {other_words(self.n * 31 + i, 10)}."
        return card


@pytest.fixture(autouse=True)
def clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    shutil.rmtree(settings.sites_dir, ignore_errors=True)
    monkeypatch.setattr(jobs, "run_inline", True)
    monkeypatch.setattr(openrouter.time, "sleep", lambda s: None)
    openrouter._catalog.clear()
    from sitegen.core import photos

    monkeypatch.setattr(photos, "catalog_price", lambda model: None)


@pytest.fixture
def llm() -> FakeLlm:
    return FakeLlm()


@pytest.fixture
def client(llm: FakeLlm) -> Iterator[TestClient]:
    app.dependency_overrides[llm_dep] = lambda: llm
    #чтоб 500 проверять как ответ
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def core_company(client: TestClient, **body: Any) -> int:
    # только этап 1: общие факты, без утверждения
    r = client.post("/api/companies/generate", json=body)
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "done", job
    return int(job["result_id"])


def run_job(client: TestClient, url: str, **body: Any) -> dict[str, Any]:
    r = client.post(url, json=body)
    assert r.status_code == 200, r.text
    job: dict[str, Any] = r.json()
    return job


def make_company(client: TestClient, **body: Any) -> int:
    # всё кроме финального утверждения
    company_id = core_company(client, **body)
    assert client.post(f"/api/companies/{company_id}/approve-facts").status_code == 200
    #после разделов проверка идёт сама
    job = run_job(client, f"/api/companies/{company_id}/sections")
    assert job["status"] == "done", job
    return company_id


def approved_company(client: TestClient, **body: Any) -> int:
    company_id = make_company(client, **body)
    r = client.post(f"/api/companies/{company_id}/approve")
    assert r.status_code == 200, r.text
    return company_id


def make_site(client: TestClient, company_id: int, **body: Any) -> dict[str, Any]:
    payload = {"company_id": company_id, "language": "ru", **body}
    r = client.post("/api/sites", json=payload)
    assert r.status_code == 200, r.text
    job: dict[str, Any] = r.json()
    return job
