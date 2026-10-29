import base64
import io
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from sitegen.clients.openrouter import Budget, generate_image
from sitegen.core import builder, consistency, photos
from sitegen.core.photos import catalog_price as real_catalog_price
from sitegen.deps import image_dep
from sitegen.errors import AppError, CostLimit, LlmError
from sitegen.main import app
from tests.conftest import approved_company, core_company, example, make_site


def png(color: str = "red", size: tuple[int, int] = (800, 600)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class FakeImages:
    # вместо image модели, $0.04 за штуку
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.error: Exception | None = None
        self.color = "red"

    def __call__(self, model: str, prompt: str, budget: Budget, client: Any = None) -> bytes:
        budget.check()
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        budget.add(0.04)
        return png(self.color)


@pytest.fixture
def images(client: TestClient) -> FakeImages:
    fake = FakeImages()
    app.dependency_overrides[image_dep] = lambda: fake
    return fake


def photo_job(client: TestClient, cid: int, **body: Any) -> dict[str, Any]:
    r = client.post(f"/api/companies/{cid}/photos", json={"max_cost": 1.0, **body})
    assert r.status_code == 200, r.text
    job: dict[str, Any] = r.json()
    return job


def test_photos_need_approved_facts(client: TestClient, images: FakeImages):
    cid = core_company(client, aspects=[])
    job = photo_job(client, cid)
    assert job["status"] == "error"
    assert "утвердите общие факты" in job["error"]
    assert images.prompts == []


def test_photos_for_whole_team(client: TestClient, images: FakeImages):
    cid = approved_company(client, aspects=[])
    company = client.get(f"/api/companies/{cid}").json()
    people = company["data"]["people"]
    assert company["state"]["photos"] == [False] * len(people)

    job = photo_job(client, cid)
    assert job["status"] == "done"
    assert job["cost"] == pytest.approx(0.04 * len(people))
    after = client.get(f"/api/companies/{cid}").json()
    assert after["state"]["photos"] == [True] * len(people)
    assert after["cost"] == pytest.approx(company["cost"] + 0.04 * len(people))
    # фото не меняют факты: утверждение остаётся
    assert after["status"] == "approved"

    r = client.get(f"/api/companies/{cid}/photos/0")
    assert r.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(r.content))
    assert img.size == (photos.SIZE, photos.SIZE)
    assert client.get(f"/api/companies/{cid}/photos/99").status_code == 404


def test_prompt_describes_fictional_person(client: TestClient, images: FakeImages):
    cid = approved_company(client, aspects=[])
    photo_job(client, cid)
    person = client.get(f"/api/companies/{cid}").json()["data"]["people"][0]
    prompt = images.prompts[0]
    assert person["name"] in prompt
    assert person["role"] in prompt
    assert "fictional person" in prompt
    assert "does not resemble any real" in prompt
    assert "No text, no logos" in prompt


def test_only_missing_photos_unless_forced(client: TestClient, images: FakeImages):
    cid = approved_company(client, aspects=[])
    photo_job(client, cid)
    count = len(images.prompts)
    assert photo_job(client, cid)["cost"] == 0
    assert len(images.prompts) == count
    photo_job(client, cid, force=True)
    assert len(images.prompts) == count * 2


def test_new_person_gets_no_old_photo(client: TestClient, images: FakeImages):
    cid = approved_company(client, aspects=[])
    photo_job(client, cid)
    data = client.get(f"/api/companies/{cid}").json()["data"]
    data["people"][3]["name"] = "Новый Человек"
    client.put(f"/api/companies/{cid}", json=data)
    st = client.get(f"/api/companies/{cid}").json()["state"]
    assert st["photos"][3] is False
    assert st["photos"][0] is True


def test_failed_photo_and_limit(client: TestClient, images: FakeImages):
    cid = approved_company(client, aspects=[])
    images.error = LlmError("модель не нарисовала картинку")
    job = photo_job(client, cid)
    assert job["status"] == "done"
    assert "не нарисовала" in job["warning"]

    images.error = None
    # хватает на два фото
    job = photo_job(client, cid, max_cost=0.08)
    assert "лимит" in job["warning"]
    assert client.get(f"/api/companies/{cid}").json()["state"]["photos"].count(True) == 2


def test_site_uses_generated_photos(client: TestClient, images: FakeImages):
    cid = approved_company(client, aspects=[])
    photo_job(client, cid)
    sid = make_site(client, cid)["result_id"]
    page = client.get(f"/preview/{sid}/company.html").text
    assert "assets/team/p1.jpg" in page
    assert client.get(f"/preview/{sid}/assets/team/p1.jpg").status_code == 200
    assert client.get(f"/api/sites/{sid}").json()["report"]["ok"] is True


def test_site_without_photos_uses_placeholders(client: TestClient):
    cid = approved_company(client, aspects=[])
    sid = make_site(client, cid)["result_id"]
    assert "assets/team/p1.svg" in client.get(f"/preview/{sid}/company.html").text


def test_process_rejects_garbage_and_crops():
    with pytest.raises(AppError):
        photos.process(b"not an image")
    out = Image.open(io.BytesIO(photos.process(png(size=(1200, 400)))))
    assert out.size == (512, 512)
    assert out.format == "JPEG"


def test_photo_check_counts_jpg_and_svg():
    data = example("kapitalklar")
    files = builder.render_site(data, data, "ru", "ocean", "sans", photos=[png(), None, None, None, None])
    assert "assets/team/p1.jpg" in files
    assert "assets/team/p2.svg" in files
    pages = {n: b.decode() for n, b in files.items() if n.endswith(".html")}
    assert consistency.check_site(data, data, pages, files, "ru")["ok"]


# ---------- клиент OpenRouter для картинок ----------

def image_reply(raw: bytes, cost: float = 0.04) -> httpx.Response:
    url = "data:image/png;base64," + base64.b64encode(raw).decode()
    body = {"choices": [{"message": {"content": "", "images": [{"type": "image_url", "image_url": {"url": url}}]}}],
            "usage": {"cost": cost}}  # fmt: skip
    return httpx.Response(200, json=body)


def client_with(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_generate_image_request_and_answer():
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read())
        return image_reply(png())

    budget = Budget(1)
    raw = generate_image("google/x-image", "портрет", budget, client_with(handler))
    assert Image.open(io.BytesIO(raw)).size == (800, 600)
    assert seen["body"]["modalities"] == ["image", "text"]
    assert budget.spent == pytest.approx(0.04)


def test_generate_image_retries_when_no_image():
    answers = iter([httpx.Response(200, json={"choices": [{"message": {"content": "не могу"}}]}), image_reply(png())])
    assert generate_image("m/m", "p", Budget(1), client_with(lambda r: next(answers)))


@pytest.mark.parametrize(("code", "text"), [(401, "ключ"), (402, "денег"), (400, "не рисует")])
def test_generate_image_client_errors(code: int, text: str):
    with pytest.raises(LlmError, match=text):
        generate_image("m/m", "p", Budget(1), client_with(lambda r: httpx.Response(code, json={})))


def test_generate_image_gives_up_and_respects_limit():
    with pytest.raises(LlmError, match="не нарисовала"):
        generate_image("m/m", "p", Budget(1), client_with(lambda r: httpx.Response(503)))
    budget = Budget(0.01)
    budget.add(0.02)
    with pytest.raises(CostLimit):
        generate_image("m/m", "p", budget, client_with(lambda r: image_reply(png())))


def test_image_models_in_catalog(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from sitegen.clients import openrouter

    catalog = [
        {"id": "google/gemini-3.1-flash-lite-image", "name": "x", "prompt": 0.0, "completion": 0.0,
         "image_output": 0.00003, "makes_images": True},
        {"id": "acme/painter", "name": "y", "prompt": 0.0, "completion": 0.0,
         "image_output": 0.0001, "makes_images": True},
        {"id": "acme/writer", "name": "z", "prompt": 0.0, "completion": 0.0,
         "image_output": 0.0, "makes_images": False},
    ]  # fmt: skip
    monkeypatch.setattr(openrouter, "list_models", lambda http=None: catalog)
    body = client.get("/api/models").json()
    lite = next(m for m in body["image_presets"] if m["id"] == "google/gemini-3.1-flash-lite-image")
    assert lite["per_image"] == pytest.approx(0.039)
    assert body["image_others"] == ["acme/painter"]
    assert client.get("/api/config").json()["default_image_model"] == "google/gemini-3.1-flash-lite-image"


def test_limit_is_not_overshot_by_one_more_photo(client: TestClient, images: FakeImages):
    cid = approved_company(client, aspects=[])
    # $0.10 и фото по $0.04: третье уже не влезло бы
    job = photo_job(client, cid, max_cost=0.1)
    assert job["cost"] == pytest.approx(0.08)
    assert job["cost"] <= job["limit"]
    assert "не хватает на ещё одно фото" in job["warning"]


def test_price_from_catalog_stops_before_first_photo(
    client: TestClient, images: FakeImages, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(photos, "catalog_price", lambda model: 0.05)
    cid = approved_company(client, aspects=[])
    job = photo_job(client, cid, max_cost=0.04)
    assert job["cost"] == 0
    assert images.prompts == []
    assert "не хватает" in job["warning"]


def test_catalog_price_from_tariff(monkeypatch: pytest.MonkeyPatch):
    from sitegen.clients import openrouter

    items = [{"id": "a/img", "image_output": 0.00003}, {"id": "a/text", "image_output": 0.0}]
    monkeypatch.setattr(openrouter, "list_models", lambda http=None: items)
    #conftest подменяет её только в photos
    assert real_catalog_price("a/img") == pytest.approx(0.039)
    assert real_catalog_price("a/text") is None
    assert real_catalog_price("нет/такой") is None


def test_team_gets_different_looks():
    card = example("kapitalklar")
    prompts = [photos.prompt_for(p, card) for p in card["people"]]
    looks = [photos.look_for(p, card) for p in card["people"]]
    assert len(set(prompts)) == len(prompts)
    # фонов больше чем людей, повторов нет
    assert len({look["background"] for look in looks}) == len(looks)
    assert len({look["pose"] for look in looks}) == min(len(looks), len(photos.POSES))
    staff = [look["clothing"] for p, look in zip(card["people"], looks, strict=True) if p["level"] == "staff"]
    assert len(set(staff)) == len(staff)


def test_look_is_stable_and_matches_level():
    card = example("kapitalklar")
    ceo = next(p for p in card["people"] if p["level"] == "ceo")
    other_bio = dict(card, people=[dict(p, bio="другая биография") for p in card["people"]])
    assert photos.look_for(ceo, card) == photos.look_for(ceo, other_bio)
    assert photos.look_for(ceo, card)["clothing"] in photos.CLOTHING["ceo"]
    staff = next(p for p in card["people"] if p["level"] == "staff")
    assert photos.look_for(staff, card)["clothing"] in photos.CLOTHING["staff"]
    prompt = photos.prompt_for(ceo, card)
    assert "{" not in prompt
    assert photos.look_for(ceo, card)["background"] in prompt
    # у другой компании свой набор образов
    other = dict(card, brand="Другая", legal_name="Другая GmbH")
    assert [photos.look_for(p, card) for p in card["people"]] != [photos.look_for(p, other) for p in card["people"]]


def test_redraw_one_person(client: TestClient, images: FakeImages):
    cid = approved_company(client, aspects=[])
    photo_job(client, cid)
    before = [client.get(f"/api/companies/{cid}/photos/{i}").content for i in range(3)]
    count = len(images.prompts)
    person = client.get(f"/api/companies/{cid}").json()["data"]["people"][1]

    images.color = "blue"
    job = photo_job(client, cid, only=1)
    assert job["status"] == "done"
    assert job["cost"] == pytest.approx(0.04)
    #ушёл один запрос и как раз про него
    assert len(images.prompts) == count + 1
    assert person["name"] in images.prompts[-1]
    after = [client.get(f"/api/companies/{cid}/photos/{i}").content for i in range(3)]
    assert after[0] == before[0] and after[2] == before[2]
    assert after[1] != before[1]


def test_redraw_one_bad_index(client: TestClient, images: FakeImages):
    cid = approved_company(client, aspects=[])
    job = photo_job(client, cid, only=99)
    assert job["status"] == "error"
    assert "Нет такого сотрудника" in job["error"]
    assert images.prompts == []
