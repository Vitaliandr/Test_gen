from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeLlm, approved_company, make_site


def test_reopening_saved_results_is_free(client: TestClient, llm: FakeLlm, monkeypatch: pytest.MonkeyPatch,
                                         caplog: pytest.LogCaptureFixture):
    company_id = approved_company(client)
    job = make_site(client, company_id, language="de")
    site_id = job["result_id"]
    calls = len(llm.calls)
    spent = client.get("/api/spend").json()["total"]

    # наружу ходить нельзя вообще,
    #кроме testserver, через него ходит TestClient
    send = httpx.Client.send

    def no_network(self: httpx.Client, request: httpx.Request, **kw: Any) -> httpx.Response:
        if request.url.host != "testserver":
            raise AssertionError(f"запрос наружу при повторном открытии: {request.url}")
        return send(self, request, **kw)

    monkeypatch.setattr(httpx.Client, "send", no_network)
    caplog.set_level("DEBUG")

    urls = [
        "/api/companies",
        f"/api/companies/{company_id}",
        f"/api/companies/{company_id}/download",
        "/api/sites",
        f"/api/sites?company_id={company_id}",
        f"/api/sites/{site_id}",
        f"/api/sites/{site_id}/download",
        f"/preview/{site_id}/index.html",
        f"/preview/{site_id}/product.html",
        f"/api/jobs/{job['id']}",
        "/api/spend",
        "/api/config",
        "/api/key",
    ]
    for url in urls:
        r = client.get(url)
        assert r.status_code == 200, (url, r.text)
        assert "sk-or-test-key" not in r.content.decode("utf-8", "ignore"), url

    assert len(llm.calls) == calls
    assert client.get("/api/spend").json()["total"] == spent
    assert "sk-or-test-key" not in caplog.text
