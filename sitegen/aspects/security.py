import re
from typing import Any

from pydantic import BaseModel, Field

from sitegen.aspects.base import Aspect, Ctx, Page, affirmed, result, unsupported_features
from sitegen.core.text import norm, walk_strings

# компания выдуманная, сертификатов у неё нет
CERTIFICATES = re.compile(
    r"ISO\s?/?\s?(?:IEC\s?)?27001|SOC\s?[12]|\bTÜV\b|\bBSI\b|\bC5\b|PCI[\s-]?DSS|сертифицирован|zertifiziert|certified",
    re.I,
)
ABSOLUTE = re.compile(r"100\s?%\s*(?:безопасн|защищ|sicher)|абсолютн\w+ безопасн|absolut sicher|не может быть взломан", re.I)


class Measure(BaseModel):
    area: str = Field(min_length=3, max_length=80)
    description: str = Field(min_length=40, max_length=500)


class SecurityInfo(BaseModel):
    summary: str = Field(min_length=40, max_length=500)
    measures: list[Measure] = Field(min_length=4, max_length=8)
    data_handling: str = Field(min_length=60, max_length=800)
    incident_response: str = Field(min_length=40, max_length=600)


class SecurityAspect(Aspect):
    key = "security"
    number = 7
    title = "Безопасность"
    model = SecurityInfo
    pages = (Page("security", "security.html", {"ru": "Безопасность", "de": "Sicherheit"}, "nav", "security"),)
    translatable = frozenset({"summary", "area", "description", "data_handling", "incident_response"})
    labels = {
        "security": "Безопасность", "measures": "Меры защиты", "area": "Направление",
        "data_handling": "Как обращаемся с данными клиента", "incident_response": "Действия при инциденте",
    }  # fmt: skip
    strings = {
        "ru": {"measures": "Меры защиты", "data_handling": "Как мы обращаемся с данными клиента",
               "incident": "Если случился инцидент", "report_to": "Сообщить о проблеме можно на"},
        "de": {"measures": "Schutzmaßnahmen", "data_handling": "Wie wir mit Kundendaten umgehen",
               "incident": "Wenn ein Vorfall eintritt", "report_to": "Melden können Sie ein Problem unter"},
    }  # fmt: skip
    skeleton = """Структура JSON:
{
  "summary": "как компания подходит к безопасности, 2-3 предложения",
  "measures": [{"area": "направление, например контроль доступа", "description": "что именно делается"}],
  "data_handling": "что происходит с данными клиента: получение, хранение, удаление",
  "incident_response": "что компания делает при инциденте, без адреса почты, его добавит система"
}
measures: от 4 до 8 пунктов."""

    def prompt(self, ctx: Ctx) -> str:
        return """Подготовь раздел сайта о безопасности: как компания защищает данные клиентов при работе продукта.
Правила:
- меры описывай реалистично для компании такого размера: контроль доступа, шифрование при передаче, разделение данных клиентов, журналы действий, обучение сотрудников, проверка поставщиков
- не заявляй сертификаты и аттестации (ISO 27001, SOC 2, TÜV и подобные), их у компании нет
- не пиши «абсолютно безопасно», «100% защита» и подобные обещания
- не описывай функции, которых нет у продукта: личный кабинет, клиентский портал
- data_handling согласуй с входными данными и ограничениями продукта из фактов
- адрес почты не пиши, система добавит контакты из фактов"""

    def check(self, ctx: Ctx, data: Any) -> list[str]:
        issues = []
        texts = list(walk_strings(data.model_dump()))
        if affirmed(CERTIFICATES, texts):
            issues.append("заявлены сертификаты или аттестации, которых нет в фактах")
        if affirmed(ABSOLUTE, texts):
            issues.append("абсолютные обещания безопасности недопустимы")
        found = unsupported_features(ctx, walk_strings(data.model_dump()))
        if found:
            issues.append(f"упомянуты функции, которых нет у продукта: {', '.join(found)}")
        return issues

    def meta(self, data: dict[str, Any], facts: dict[str, Any]) -> str:
        return str(data["summary"])

    def check_site(self, orig: dict[str, Any], card: dict[str, Any], texts: dict[str, str]) -> list[dict[str, Any]]:
        page = texts.get("security.html", "")
        areas = [m["area"] for m in card["sections"]["security"]["measures"]]
        missing = [a for a in areas if norm(a) not in page]
        email = orig["contacts"]["email"]
        return [
            result("Безопасность: все меры защиты на странице", not missing, ", ".join(missing)),
            result("Безопасность: указана почта для сообщений об инцидентах", email in page),
        ]
