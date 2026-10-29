import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from sitegen import main
from sitegen.background import jobs
from sitegen.errors import AppError
from sitegen.settings import settings


def test_health(client: TestClient):
    assert client.get("/health").json() == {"status": "ok"}


def test_panel_page_is_served(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>TestGen</title>" in r.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/theme.js").status_code == 200


def test_security_headers(client: TestClient):
    r = client.get("/api/config")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-cache"
    # swagger грузит скрипты с cdn
    assert "content-security-policy" not in client.get("/docs").headers


def test_request_id_is_echoed_or_generated(client: TestClient):
    assert client.get("/health", headers={"x-request-id": "abc-123"}).headers["x-request-id"] == "abc-123"
    generated = client.get("/health", headers={"x-request-id": "bad id!"}).headers["x-request-id"]
    assert generated != "bad id!"
    assert len(generated) == 12


def test_foreign_origin_post_is_rejected(client: TestClient):
    r = client.post("/api/companies/generate", json={}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    ok = client.post("/api/companies/generate", json={}, headers={"origin": "http://testserver"})
    assert ok.status_code == 200


def test_unknown_host_is_rejected(client: TestClient):
    assert client.get("/health", headers={"host": "evil.example"}).status_code == 400


def test_validation_errors_are_in_russian(client: TestClient):
    r = client.post("/api/sites", json={"language": "ru"})
    assert r.status_code == 422
    assert "Компания: обязательное поле" in r.json()["detail"]
    r = client.post("/api/sites", json={"company_id": "abc", "language": "ru"})
    assert "неверный тип" in r.json()["detail"]


def test_unknown_job(client: TestClient):
    assert client.get("/api/jobs/nope").status_code == 404


def test_job_runs_in_thread(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(jobs, "run_inline", False)
    job = jobs.start(lambda j: 42)
    for _ in range(100):
        if job.status != "running":
            break
        time.sleep(0.02)
    assert (job.status, job.result_id) == ("done", 42)
    assert jobs.get(job.id) is job


def test_failed_job_keeps_message():
    def work(job: jobs.Job) -> int:
        raise AppError("понятная причина")

    job = jobs.start(work)
    assert (job.status, job.error) == ("error", "понятная причина")


def test_old_jobs_are_dropped(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(jobs, "MAX_JOBS", 3)
    started = [jobs.start(lambda j: 1) for _ in range(5)]
    assert jobs.get(started[0].id) is None
    assert jobs.get(started[-1].id) is started[-1]


def test_migrations_create_tables(tmp_path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite:///{tmp_path}/migrated.db"
    monkeypatch.setattr(settings, "database_url", url)
    main.run_migrations()
    engine = create_engine(url)
    names = set(inspect(engine).get_table_names())
    engine.dispose()
    assert {"companies", "sites", "alembic_version"} <= names
