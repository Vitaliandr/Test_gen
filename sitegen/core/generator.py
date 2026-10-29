import random
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sitegen import catalog
from sitegen.card import Company, CompanyContent, Contacts
from sitegen.clients.openrouter import Budget, Llm
from sitegen.core import consistency, similarity
from sitegen.core.text import slugify
from sitegen.errors import AppError

Stage = Callable[[str], None]

LANG_NAMES = {"ru": "русском", "de": "немецком"}

SYSTEM = """Ты готовишь тестовые данные: придумываешь вымышленную B2B-компанию.
Правила:
- всё выдумано, не называй реальные компании, банки, фонды, вузы и реальных людей
- прошлые места работы описывай обобщённо, например «крупный банк» или «консалтинговая компания»
- не пиши регистрационные номера, налоговые номера, адреса и телефоны, их добавит система
- тексты конкретные и не противоречат друг другу: продукт, ограничения и ответы FAQ согласованы
- у людей правдоподобные для страны компании имена, разный опыт и разный путь в профессии
- не описывай как работающие то, чего на сайте нет: личный кабинет, регистрацию и вход, загрузку файлов, формы заявок;
  связаться с компанией можно только по почте и телефону
Верни только один JSON-объект, без markdown и пояснений."""

SKELETON = """Структура JSON:
{
  "brand": "название бренда",
  "legal_name": "бренд и организационно-правовая форма, например Brand Analytics GmbH",
  "founding_year": 2019,
  "employee_count": 25,
  "tagline": "короткое предложение компании, до 140 символов",
  "value_proposition": "2-3 предложения о том, что получает клиент",
  "advantages": ["3-5 преимуществ, по одному предложению"],
  "history": "история основания, 4-6 предложений, обязательно с годом основания",
  "specialization": "в чём компания сильна и чем отличается",
  "audience": "целевая аудитория",
  "client_problem": "проблема клиента, которую решает продукт",
  "product": {
    "name": "название продукта",
    "summary": "что это за услуга",
    "inputs": ["входные данные"],
    "process": ["3-6 шагов работы по порядку"],
    "outputs": ["результат работы"],
    "limitations": ["честные ограничения"],
    "scenarios": [
      {"title": "название сценария", "situation": "в какой ситуации клиент приходит", "how_it_helps": "как продукт решает задачу", "result": "что клиент получает"}
    ]
  },
  "faq": [{"question": "вопрос", "answer": "ответ"}],
  "people": [
    {"name": "Имя Фамилия", "role": "должность", "level": "ceo или head или staff", "bio": "2-3 предложения о пути"}
  ]
}
scenarios: 3-4 сценария использования, сценарии согласованы с ограничениями продукта. faq ровно 5 пунктов. people: ровно 1 ceo, ровно 2 head (руководители отделов) и минимум 2 staff (сотрудники)."""


def resolve_params(req: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    def pick(value: Any, options: Any) -> Any:
        return rng.choice(list(options)) if value in (None, "", "random") else value

    country = pick(req.get("country"), catalog.COUNTRIES)
    scale = pick(req.get("scale"), catalog.SCALES)
    info = catalog.COUNTRIES[country]
    scale_info = catalog.SCALES[scale]
    return {
        "country": country,
        "direction": pick(req.get("direction"), catalog.DIRECTIONS),
        "service_type": pick(req.get("service_type"), catalog.SERVICE_TYPES),
        "scale": scale,
        "language": req.get("language") or "ru",
        "brand": (req.get("brand") or "").strip(),
        "city": rng.choice(list(info["cities"])),
        "legal_form": rng.choice(info["legal_forms"][scale]),
        "founding_year": datetime.now().year - rng.randint(*scale_info["age"]),
        "employee_count": rng.randint(*scale_info["employees"]),
        "niche": rng.choice(catalog.NICHES),
        "founder": rng.choice(catalog.FOUNDERS),
    }


def make_contacts(r: dict[str, Any], brand: str, rng: random.Random) -> Contacts:
    info = catalog.COUNTRIES[r["country"]]
    city = info["cities"][r["city"]]
    # у двузначного кода номер длиннее
    length = 8 if len(city["area"]) == 2 else 7
    rest = str(rng.randint(2, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(length - 1))
    half = 4 if length == 8 else 3
    prefix = rng.choice(city["plz"])
    postal = prefix + "".join(str(rng.randint(0, 9)) for _ in range(info["postal_digits"] - len(prefix)))
    street = info["street_format"].format(street=rng.choice(info["streets"]), number=rng.randint(1, 120))
    return Contacts(
        city=r["city"],
        postal_code=postal,
        street=street,
        phone=f"+{info['phone_code']} {city['area']} {rest[:half]} {rest[half:]}",
        email=f"info@{slugify(brand)}.{info['tld']}",
    )


def build_prompt(r: dict[str, Any], existing: list[tuple[str, dict[str, Any]]]) -> list[dict[str, str]]:
    if r["brand"]:
        brand_line = f"Название бренда: «{r['brand']}», используй без изменений."
    else:
        brand_line = "Название бренда придумай сам: короткое, не похожее на известную реальную компанию."
    avoid = "; ".join(f"{brand} ({data['specialization'][:90]})" for brand, data in existing[:10])
    user = f"""Придумай компанию с такими параметрами.
{brand_line}
Страна: {catalog.country_name(r['country'], 'ru')}, город: {r['city']}.
Направление: {catalog.DIRECTIONS[r['direction']]}.
Тип сервиса: {catalog.SERVICE_TYPES[r['service_type']]}.
Масштаб: {catalog.SCALES[r['scale']]['label']}, сейчас около {r['employee_count']} сотрудников.
Год основания: {r['founding_year']}. Организационно-правовая форма: {r['legal_form']}.
Специализация, главный акцент: {r['niche']}.
Основатель: {r['founder']}.
Имена людей {catalog.COUNTRIES[r['country']]['people']}, у русских с отчеством не нужно, только имя и фамилия.
Тексты пиши на {LANG_NAMES[r['language']]} языке, имена людей и названия не переводи.
{'Уже есть такие компании, не повторяй их идеи, историю и формулировки: ' + avoid if avoid else ''}

{SKELETON}"""
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def generate(
    requested: dict[str, Any],
    model: str,
    llm: Llm,
    budget: Budget,
    stage: Stage,
    existing: list[tuple[str, dict[str, Any]]],
) -> tuple[Company, dict[str, Any]]:
    stage("Подбор параметров")
    seed = random.randrange(2**32)
    rng = random.Random(seed)
    r = resolve_params(requested, rng)

    def validate(data: dict[str, Any]) -> CompanyContent:
        if r["brand"]:
            data["brand"] = r["brand"]
        content = CompanyContent.model_validate(data)
        issues = consistency.check_content(content, r["legal_form"], [b for b, _ in existing])
        #вышел пересказ другой компании, пусть переписывает
        issues += similarity.compare(content.model_dump(), r["language"], existing)
        if issues:
            raise ValueError("; ".join(issues))
        return content

    stage("Запрос к модели, генерация карточки")
    content: CompanyContent = llm(model, build_prompt(r, existing), budget, validate=validate)

    stage("Сборка контактов и проверка")
    company = Company(
        **content.model_dump(),
        country=r["country"],
        direction=r["direction"],
        service_type=r["service_type"],
        scale=r["scale"],
        language=r["language"],
        contacts=make_contacts(r, content.brand, rng),
    )
    issues = consistency.check_company(company)
    if issues:
        raise AppError("Карточка не прошла проверку: " + "; ".join(issues))
    return company, {"requested": requested, "resolved": r, "seed": seed}
