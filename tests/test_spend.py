import pytest
from fastapi.testclient import TestClient

from tests.conftest import approved_company, core_company, make_site


def test_company_spend_includes_sites(client: TestClient):
    cid = approved_company(client, aspects=[])
    company = client.get(f"/api/companies/{cid}").json()
    assert company["spend"]["company"] == pytest.approx(company["cost"])
    assert company["spend"]["sites"] == 0

    # немецкий перевод платный, идёт в расходы
    make_site(client, cid, language="de")
    after = client.get(f"/api/companies/{cid}").json()["spend"]
    assert after["sites"] > 0
    assert after["total"] == pytest.approx(after["company"] + after["sites"])


def test_total_spend_over_all_companies(client: TestClient):
    assert client.get("/api/spend").json() == {"companies": 0, "sites": 0, "total": 0}
    first = core_company(client, aspects=[])
    second = core_company(client, aspects=[])
    total = client.get("/api/spend").json()
    costs = [client.get(f"/api/companies/{c}").json()["cost"] for c in (first, second)]
    assert total["companies"] == pytest.approx(sum(costs))
    assert total["total"] == pytest.approx(sum(costs))
