import pytest
from fastapi.testclient import TestClient

from sitegen.core import builder, consistency
from tests.conftest import approved_company, example, make_site


@pytest.mark.parametrize("theme", list(builder.THEMES))
@pytest.mark.parametrize("name", ["kapitalklar", "datenpegel"])
def test_every_theme_passes_site_checks(theme: str, name: str):
    data = example(name)
    files = builder.render_site(data, data, data["language"], "ocean", "sans", theme)
    pages = {n: b.decode() for n, b in files.items() if n.endswith(".html")}
    report = consistency.check_site(data, data, pages, files, data["language"])
    assert report["ok"], [c for c in report["checks"] if not c["ok"]]


def test_themes_look_different():
    data = example("kapitalklar")
    css = {t: builder.render_site(data, data, "ru", "ocean", "sans", t)["assets/style.css"] for t in builder.THEMES}
    assert len(set(css.values())) == len(builder.THEMES)
    editorial = builder.render_site(data, data, "ru", "ocean", "sans", "editorial")["index.html"].decode()
    assert 'class="header masthead"' in editorial
    assert data["tagline"] in editorial


@pytest.mark.parametrize("theme", list(builder.THEMES))
def test_motion_is_css_only_and_respects_reduced_motion(theme: str):
    data = example("kapitalklar")
    files = builder.render_site(data, data, "ru", "forest", "serif", theme)
    css = files["assets/style.css"].decode()
    assert "@keyframes rise" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "animation-timeline: view()" in css
    # схема цветов доходит до темы
    assert builder.SCHEMES["forest"]["primary"] in css
    assert all("<script" not in b.decode() for n, b in files.items() if n.endswith(".html"))


def test_site_with_theme_through_api(client: TestClient):
    cid = approved_company(client, aspects=[])
    job = make_site(client, cid, theme="dark", scheme="violet")
    assert job["status"] == "done"
    site = client.get(f"/api/sites/{job['result_id']}").json()
    assert site["style"]["theme"] == "dark"
    assert "radial-gradient" in client.get(f"/preview/{job['result_id']}/assets/style.css").text
    assert make_site(client, cid, theme="neon")["status"] == "error"
    assert [t["key"] for t in client.get("/api/config").json()["themes"]] == ["classic", "editorial", "dark"]


def test_home_hero_splits_long_text():
    from sitegen.core.text import sentences, split_tagline

    assert split_tagline("Превращаем тезис в карту ландшафта: кто изобретает и как быстро.") == (
        "Превращаем тезис в карту ландшафта", "Кто изобретает и как быстро",
    )
    assert split_tagline("Короткий слоган") == ("Короткий слоган", "")
    assert sentences("Первое предложение. Второе, с числом 2.5 внутри. Третье.") == [
        "Первое предложение.", "Второе, с числом 2.5 внутри.", "Третье.",
    ]


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("2. Порядок оказания услуг", "Порядок оказания услуг"),
        ("§ 3 Haftung", "Haftung"),
        ("2024 год в цифрах", "2024 год в цифрах"),
        ("30 дней на возврат", "30 дней на возврат"),
        ("152-ФЗ и данные", "152-ФЗ и данные"),
    ],
)
def test_strip_number_keeps_real_numbers(raw: str, clean: str):
    from sitegen.core.text import strip_number

    assert strip_number(raw) == clean


def test_tagline_is_not_cut_on_abbreviation():
    from sitegen.core.text import split_tagline

    text = "Проверяем отчётность эмитентов, т. е. цифры и сноски, быстрее команды"
    assert split_tagline(text) == (text, "")


def test_preview_cannot_run_scripts(client):
    from tests.conftest import approved_company, make_site

    site = make_site(client, approved_company(client))["result_id"]
    csp = client.get(f"/preview/{site}/index.html").headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src" not in csp
    assert "script-src 'self'" in client.get("/").headers["content-security-policy"]
