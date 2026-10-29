import random
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from sitegen import catalog
from sitegen.aspects.base import Aspect, Ctx, Page, result
from sitegen.core.text import norm

Key = Literal["court", "register", "vat_id", "inn", "kpp", "ogrn", "okved", "capital", "director"]

#какие реквизиты у страны, в таком порядке и выводим
KEYS = {
    "DE": ["court", "register", "vat_id", "capital", "director"],
    "RU": ["inn", "kpp", "ogrn", "okved", "capital", "director"],
}
FORMATS = {
    "court": r"^Amtsgericht [\w .()-]+$",
    "register": r"^HRB 9\d{5}$",
    "vat_id": r"^DE\d{9}$",
    "inn": r"^\d{10}$",
    "kpp": r"^\d{4}01001$",
    "ogrn": r"^1\d{12}$",
    "okved": r"^\d{2}\.\d{2}$",
    "capital": r"^\d{1,3}(?:[ .]\d{3})* (?:EUR|₽)$",
}
# минимальный уставный капитал
MIN_CAPITAL = {"GmbH": 25000, "UG": 1, "AG": 50000, "ООО": 10000, "АО": 100000}
#saas это разработка ПО, остальное обработка данных
OKVED = {"saas": "62.01", "api": "63.11", "managed": "63.11", "reports": "63.11"}


class Entry(BaseModel):
    key: Key
    value: str = Field(min_length=2, max_length=120)


class Requisites(BaseModel):
    entries: list[Entry] = Field(min_length=4, max_length=8)


def _inn_check(digits: str) -> int:
    weights = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    return sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % 11 % 10


def _ogrn_check(digits: str) -> int:
    return int(digits) % 11 % 10


def _vat_check(digits: str) -> int:
    # USt-IdNr считается по ISO 7064 MOD 11,10
    product = 10
    for d in digits:
        total = (int(d) + product) % 10 or 10
        product = total * 2 % 11
    return (11 - product) % 10


def checksum_ok(key: str, value: str) -> bool:
    digits = value[2:] if key == "vat_id" else value
    body, last = digits[:-1], int(digits[-1])
    check = {"inn": _inn_check, "ogrn": _ogrn_check, "vat_id": _vat_check}[key]
    return check(body) == last


def _broken(body: str, check: int) -> str:
    #контрольную цифру портим специально, чтоб номер не совпал с настоящей фирмой
    return body + str((check + 1) % 10)


def legal_form(ctx: Ctx) -> str:
    name = ctx.facts["legal_name"]
    return next((f for f in MIN_CAPITAL if re.search(rf"(?<!\w){f}(?!\w)", name)), "")


def _money(amount: int, country: str) -> str:
    sep = "." if country == "DE" else " "
    return f"{amount:,}".replace(",", sep) + (" EUR" if country == "DE" else " ₽")


def _amount(value: str) -> int:
    return int(re.sub(r"\D", "", value) or 0)


class RequisitesAspect(Aspect):
    key = "requisites"
    number = 3
    title = "Страновые реквизиты"
    model = Requisites
    by_code = True
    skeleton = ""
    pages = (Page("requisites", "requisites.html", {"ru": "Реквизиты", "de": "Firmendaten"}, "footer", "requisites"),)
    labels = {"requisites": "Реквизиты", "entries": "Реквизиты", "key": "Реквизит", "value": "Значение"}
    strings = {
        "ru": {"court": "Регистрационный суд", "register": "Номер в торговом реестре", "vat_id": "USt-IdNr.",
               "inn": "ИНН", "kpp": "КПП", "ogrn": "ОГРН", "okved": "Основной код ОКВЭД",
               "capital": "Уставный капитал", "director": "Руководитель", "legal_name": "Полное наименование",
               "address": "Юридический адрес"},
        "de": {"court": "Registergericht", "register": "Registernummer", "vat_id": "Umsatzsteuer-ID",
               "inn": "INN (Steuernummer)", "kpp": "KPP", "ogrn": "OGRN (Registernummer)",
               "okved": "Haupttätigkeit (OKWED)", "capital": "Stammkapital", "director": "Geschäftsführung",
               "legal_name": "Firma", "address": "Sitz"},
    }  # fmt: skip

    def prompt(self, ctx: Ctx) -> str:
        return ""

    def build(self, ctx: Ctx) -> dict[str, Any]:
        f = ctx.facts
        country, city = f["country"], f["contacts"]["city"]
        info = catalog.COUNTRIES[country]["cities"][city]
        # пересоздали раздел, а номера те же
        rng = random.Random(f"{f['brand']}|{f['legal_name']}")
        form = legal_form(ctx)
        values: dict[str, str] = {"director": ctx.ceo}
        if country == "DE":
            vat = "".join(rng.choice("0123456789") for _ in range(8))
            values["court"] = info["court"]
            #HRB от 900000 ещё никому не выдавали
            values["register"] = f"HRB {rng.randint(900000, 999999)}"
            values["vat_id"] = "DE" + _broken(vat, _vat_check(vat))
            capital = {"UG": rng.choice([1000, 2500, 5000]), "AG": rng.choice([50000, 100000])}.get(form, 25000)
        else:
            region, office = info["region"], f"{rng.randint(1, 50):02d}"
            inn = region + office + "".join(rng.choice("0123456789") for _ in range(5))
            ogrn = "1" + f"{f['founding_year'] % 100:02d}" + region + office + f"{rng.randint(0, 99999):05d}"
            values["inn"] = _broken(inn, _inn_check(inn))
            values["kpp"] = region + office + "01001"
            values["ogrn"] = _broken(ogrn, _ogrn_check(ogrn))
            values["okved"] = OKVED.get(f["service_type"], "63.11")
            capital = rng.choice([100000, 500000]) if form == "АО" else rng.choice([10000, 50000, 100000])
        values["capital"] = _money(capital, country)
        return {"entries": [{"key": k, "value": values[k]} for k in KEYS[country]]}

    def check(self, ctx: Ctx, data: Any) -> list[str]:
        f = ctx.facts
        country, city = f["country"], f["contacts"]["city"]
        info = catalog.COUNTRIES.get(country, {}).get("cities", {}).get(city, {})
        values = {e.key: e.value for e in data.entries}
        issues = []
        if list(values) != KEYS.get(country, []):
            issues.append(f"для страны {country} нужны реквизиты: {', '.join(KEYS.get(country, []))}")
        for key, value in values.items():
            if key in FORMATS and not re.match(FORMATS[key], value):
                issues.append(f"реквизит {key} не в формате страны: {value}")
            elif key in ("inn", "ogrn", "vat_id") and checksum_ok(key, value):
                issues.append(f"реквизит {key} с верной контрольной цифрой может совпасть с реальной организацией")
        if values.get("director") != ctx.ceo:
            issues.append(f"руководитель в реквизитах не {ctx.ceo}")
        if "court" in values and values["court"] != info.get("court"):
            issues.append(f"регистрационный суд не по городу {city}: {info.get('court')}")
        region = info.get("region", "")
        for key in ("inn", "kpp"):
            if key in values and not values[key].startswith(region):
                issues.append(f"{key} не из региона {city} ({region})")
        if "ogrn" in values:
            if values["ogrn"][3:5] != region:
                issues.append(f"ОГРН не из региона {city} ({region})")
            if values["ogrn"][1:3] != f"{f['founding_year'] % 100:02d}":
                issues.append(f"год в ОГРН не совпадает с годом основания {f['founding_year']}")
        if "inn" in values and "kpp" in values and values["inn"][:4] != values["kpp"][:4]:
            issues.append("КПП выдан не той инспекцией, что ИНН")
        form = legal_form(ctx)
        if "capital" in values and form and _amount(values["capital"]) < MIN_CAPITAL[form]:
            issues.append(f"уставный капитал меньше минимума для {form}: {_money(MIN_CAPITAL[form], country)}")
        return issues

    def meta(self, data: dict[str, Any], facts: dict[str, Any]) -> str:
        return f"{facts['legal_name']}: " + ", ".join(e["value"] for e in data["entries"][:3])

    def check_site(self, orig: dict[str, Any], card: dict[str, Any], texts: dict[str, str]) -> list[dict[str, Any]]:
        page = texts.get("requisites.html", "")
        values = [e["value"] for e in orig["sections"]["requisites"]["entries"]] + [orig["legal_name"]]
        missing = [v for v in values if norm(v) not in page]
        return [result("Реквизиты: все значения и юрлицо на странице", not missing, ", ".join(missing))]
