from pathlib import Path

from fastapi.testclient import TestClient

from sitegen.core import sites
from sitegen.settings import settings
from tests.conftest import approved_company, make_site


def test_delete_site_removes_files_and_renumbers(client: TestClient):
    cid = approved_company(client)
    first = make_site(client, cid)["result_id"]
    second = make_site(client, cid)["result_id"]
    assert sites.site_dir(first).is_dir()

    assert client.delete(f"/api/sites/{first}").status_code == 204
    assert not sites.site_dir(first).exists()
    assert client.get(f"/api/sites/{first}").status_code == 404
    assert client.get(f"/preview/{first}/index.html").status_code == 404
    # версии считаются по оставшимся, вторая стала первой
    assert client.get(f"/api/sites/{second}").json()["version"] == 1
    assert client.delete(f"/api/sites/{first}").status_code == 404


def test_delete_company_takes_sites_and_photos(client: TestClient):
    cid = approved_company(client)
    other = approved_company(client)
    site = make_site(client, cid)["result_id"]
    kept = make_site(client, other)["result_id"]
    media = Path(settings.media_dir) / str(cid)
    media.mkdir(parents=True, exist_ok=True)
    (media / "x.jpg").write_bytes(b"jpg")

    assert client.delete(f"/api/companies/{cid}").status_code == 204
    assert client.get(f"/api/companies/{cid}").status_code == 404
    assert client.get(f"/api/sites/{site}").status_code == 404
    assert not sites.site_dir(site).exists()
    assert not media.exists()
    # чужое не трогаем
    assert [c["id"] for c in client.get("/api/companies").json()] == [other]
    assert client.get(f"/api/sites/{kept}").status_code == 200
    assert client.delete(f"/api/companies/{cid}").status_code == 404


def test_delete_from_other_site_is_refused(client: TestClient):
    cid = approved_company(client)
    r = client.delete(f"/api/companies/{cid}", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.get(f"/api/companies/{cid}").status_code == 200


def test_no_delete_while_job_runs(client: TestClient, monkeypatch):
    from sitegen.background import jobs

    cid = approved_company(client)
    site = make_site(client, cid)["result_id"]
    monkeypatch.setattr(jobs, "busy", lambda: True)
    r = client.delete(f"/api/companies/{cid}")
    assert r.status_code == 400
    assert "генерация" in r.json()["detail"]
    assert client.delete(f"/api/sites/{site}").status_code == 400
    assert client.get(f"/api/companies/{cid}").status_code == 200
