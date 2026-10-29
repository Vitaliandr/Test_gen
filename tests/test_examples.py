import json
from pathlib import Path

import pytest

from sitegen.card import Company
from sitegen.core import consistency

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name / "company.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["zitara", "lavirt"])
@pytest.mark.parametrize("theme", ["classic", "editorial", "dark"])
def test_example_card_and_site_are_in_place(name: str, theme: str):
    data = load(name)
    card = Company.model_validate(data)
    assert consistency.check_company(card) == []
    assert len(card.people) >= 5
    site = EXAMPLES / name / f"site-{theme}"
    pages = ("index", "product", "security", "references", "company", "legal", "requisites", "privacy")
    for page in [*(f"{p}.html" for p in pages), "favicon.svg", "assets/style.css"]:
        assert (site / page).is_file(), page
    assert set(card.sections) == {"legal", "requisites", "privacy", "security", "references"}
    company_page = (site / "company.html").read_text(encoding="utf-8")
    assert card.contacts.phone in company_page
    # у примеров настоящие фото, а не силуэты
    assert len(list((site / "assets" / "team").glob("*.jpg"))) == len(card.people)
    assert (site / "index.html").read_text(encoding="utf-8").count(f'lang="{card.language}"') == 1


def test_examples_cover_both_countries_and_scales():
    de, ru = load("zitara"), load("lavirt")
    assert (de["country"], de["language"]) == ("DE", "de")
    assert (ru["country"], ru["language"]) == ("RU", "ru")
    assert {de["scale"], ru["scale"]} == {"small", "medium"}


def test_index_links_every_site():
    page = (EXAMPLES / "index.html").read_text(encoding="utf-8")
    for name in ("zitara", "lavirt"):
        for theme in ("classic", "editorial", "dark"):
            link = f"{name}/site-{theme}/index.html"
            assert f'href="{link}"' in page
            assert (EXAMPLES / link).is_file()
