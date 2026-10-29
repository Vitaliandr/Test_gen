import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from sitegen.core import sites
from sitegen.errors import NotFound
from sitegen.settings import settings
from tests.conftest import FakeLlm, approved_company, make_company, make_site, run_job


def test_site_needs_approved_company(client: TestClient):
    cid = make_company(client)
    job = make_site(client, cid)
    assert job["status"] == "error"
    assert "утверждённой" in job["error"]


def test_site_in_card_language_costs_nothing(client: TestClient, llm: FakeLlm):
    cid = approved_company(client)
    calls_before = len(llm.calls)
    job = make_site(client, cid, scheme="forest", font="serif")
    assert job["status"] == "done"
    assert len(llm.calls) == calls_before
    site = client.get(f"/api/sites/{job['result_id']}").json()
    assert site["cost"] == 0
    assert site["report"]["ok"] is True
    assert site["style"] == {"theme": "classic", "scheme": "forest", "font": "serif"}
    assert site["outdated"] is False


def test_preview_pages_and_assets(client: TestClient):
    cid = approved_company(client, brand="Zeta")
    sid = make_site(client, cid)["result_id"]

    index = client.get(f"/preview/{sid}/")
    assert index.status_code == 200
    assert "Zeta" in index.text
    assert 'href="product.html"' in index.text
    for path in ("product.html", "company.html", "assets/style.css", "favicon.svg", "assets/team/p5.svg"):
        assert client.get(f"/preview/{sid}/{path}").status_code == 200, path
    assert client.get(f"/preview/{sid}/nope.html").status_code == 404
    assert client.get(f"/preview/{sid}", follow_redirects=False).headers["location"] == f"/preview/{sid}/"


def test_team_has_five_people_with_photos(client: TestClient):
    cid = approved_company(client)
    sid = make_site(client, cid)["result_id"]
    html = client.get(f"/preview/{sid}/company.html").text
    assert html.count("<img") >= 5
    assert html.count("assets/team/p") == len(client.get(f"/api/companies/{cid}").json()["data"]["people"])


def test_zip_download(client: TestClient):
    cid = approved_company(client, brand="Zeta")
    sid = make_site(client, cid)["result_id"]
    r = client.get(f"/api/sites/{sid}/download")
    assert r.headers["content-type"] == "application/zip"
    from sitegen.core.companies import site_code

    assert f"site-zeta-{site_code(sid)}-ru.zip" in r.headers["content-disposition"]
    names = set(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert {"index.html", "product.html", "company.html", "favicon.svg", "assets/style.css"} <= names
    assert "sk-or" not in r.content.decode("utf-8", "ignore")


def test_german_site_translates_texts_not_facts(client: TestClient, llm: FakeLlm):
    cid = approved_company(client, brand="Zeta")
    data = client.get(f"/api/companies/{cid}").json()["data"]
    job = make_site(client, cid, language="de", model="openai/gpt-4o-mini")
    assert job["status"] == "done"
    #переводим группами: карточка и 4 раздела
    assert job["cost"] == pytest.approx(0.015)

    page = client.get(f"/preview/{job['result_id']}/company.html").text
    assert '<html lang="de"' in page
    assert "Deutschland" in page
    assert "[de] " in page
    # факты те же
    for fact in (data["contacts"]["phone"], data["contacts"]["email"], data["contacts"]["street"], "Zeta"):
        assert fact in page
    for person in data["people"]:
        assert person["name"] in page


def test_translation_needs_key_but_same_language_does_not(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    cid = approved_company(client)
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr(""))
    r = client.post("/api/sites", json={"company_id": cid, "language": "de"})
    assert r.status_code == 502
    assert make_site(client, cid)["status"] == "done"


def test_bad_site_parameters(client: TestClient):
    cid = approved_company(client)
    assert make_site(client, cid, scheme="neon")["status"] == "error"
    assert client.post("/api/sites", json={"company_id": 999, "language": "ru"}).status_code == 404
    assert client.post("/api/sites", json={"company_id": cid, "language": "xx"}).status_code == 422
    assert client.get("/api/sites/999").status_code == 404


def test_card_edit_does_not_touch_existing_site(client: TestClient):
    cid = approved_company(client)
    first = make_site(client, cid)["result_id"]
    before = client.get(f"/preview/{first}/").text

    data = client.get(f"/api/companies/{cid}").json()["data"]
    data["tagline"] = "Совсем другое предложение компании"
    assert client.put(f"/api/companies/{cid}", json=data).status_code == 200

    assert client.get(f"/preview/{first}/").text == before
    assert client.get(f"/api/sites/{first}").json()["outdated"] is True

    #факты поменялись, проходим всё заново
    assert client.post(f"/api/companies/{cid}/approve-facts").status_code == 200
    assert run_job(client, f"/api/companies/{cid}/sections")["status"] == "done"
    assert run_job(client, f"/api/companies/{cid}/review")["status"] == "done"
    approved = client.post(f"/api/companies/{cid}/approve")
    assert approved.status_code == 200, approved.text
    second = make_site(client, cid)["result_id"]
    assert "Совсем другое" in client.get(f"/preview/{second}/").text
    assert client.get(f"/api/sites/{second}").json()["outdated"] is False

    listed = client.get(f"/api/sites?company_id={cid}").json()
    assert [s["id"] for s in listed] == [second, first]
    assert client.get("/api/sites?company_id=999").json() == []


def test_reopening_does_not_call_model(client: TestClient, llm: FakeLlm):
    cid = approved_company(client)
    sid = make_site(client, cid)["result_id"]
    calls = len(llm.calls)
    client.get(f"/preview/{sid}/")
    client.get(f"/api/sites/{sid}")
    client.get(f"/api/companies/{cid}")
    assert len(llm.calls) == calls


def test_path_cannot_leave_site_folder(client: TestClient):
    cid = approved_company(client)
    sid = make_site(client, cid)["result_id"]
    #соседняя папка с настоящим файлом
    other = sites.site_dir(sid + 1)
    other.mkdir(parents=True)
    (other / "index.html").write_text("чужой сайт")
    with pytest.raises(NotFound):
        sites.file_path(sid, f"../{sid + 1}/index.html")
    with pytest.raises(NotFound):
        sites.file_path(sid, "../../test.db")
    assert client.get(f"/preview/{sid}/%2e%2e/%2e%2e/test.db").status_code == 404


def test_versions_are_counted_per_company(client: TestClient):
    first = approved_company(client)
    make_site(client, first)
    second = approved_company(client)
    make_site(client, second)
    make_site(client, second)
    versions = [s["version"] for s in client.get(f"/api/sites?company_id={second}").json()]
    assert versions == [2, 1]
    assert client.get(f"/api/sites?company_id={first}").json()[0]["version"] == 1


def test_sites_get_six_digit_codes(client: TestClient):
    from sitegen.core.companies import site_code

    sid = make_site(client, approved_company(client))["result_id"]
    body = client.get(f"/api/sites/{sid}").json()
    assert body["code"] == site_code(sid)
    assert 100000 <= body["code"] <= 999999
    assert len({site_code(i) for i in range(1, 3001)}) == 3000
