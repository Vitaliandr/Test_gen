import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from sitegen.clients.openrouter import Budget, chat_json, extract_json
from sitegen.errors import CostLimit, LlmError
from sitegen.settings import settings

MSG = [{"role": "user", "content": "привет"}]


def reply(content: str, cost: float | None = 0.01) -> httpx.Response:
    body: dict[str, Any] = {"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 10}}
    if cost is not None:
        body["usage"]["cost"] = cost
    return httpx.Response(200, json=body)


def client_with(handler: Any, models: list[dict[str, Any]] | None = None) -> httpx.Client:
    # /models отвечаем сами, в handler только запросы к модели
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": models or []})
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(route))


PRICED = [{"id": "m/m", "pricing": {"prompt": "0.000001", "completion": "0.00001"}}]


def test_max_tokens_cut_to_fit_budget():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["max_tokens"] = json.loads(request.read())["max_tokens"]
        return reply('{"a": 1}', cost=0.01)

    #0.03 / 0.00001 = 3000 токенов, просили 6000
    chat_json("m/m", MSG, Budget(0.03), client=client_with(handler, PRICED))
    assert 2900 <= seen["max_tokens"] <= 3000


def test_request_not_sent_when_budget_too_small():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return reply('{"a": 1}')

    with pytest.raises(CostLimit, match="не хватит"):
        chat_json("m/m", MSG, Budget(0.01), client=client_with(handler, PRICED))
    assert calls == []


def test_missing_cost_is_estimated_from_price():
    def handler(request: httpx.Request) -> httpx.Response:
        usage = {"prompt_tokens": 1000, "completion_tokens": 2000}
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a": 1}'}}], "usage": usage})

    budget = Budget(1)
    chat_json("m/m", MSG, budget, client=client_with(handler, PRICED))
    assert budget.known is True
    assert budget.spent == pytest.approx(1000 * 0.000001 + 2000 * 0.00001)


def test_unknown_price_keeps_full_answer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["max_tokens"] = json.loads(request.read())["max_tokens"]
        return reply('{"a": 1}')

    chat_json("m/m", MSG, Budget(0.01), client=client_with(handler, []))
    assert seen["max_tokens"] == 6000


def test_free_model_is_not_limited():
    free = [{"id": "m/m", "pricing": {"prompt": "0", "completion": "0"}}]
    answer = chat_json("m/m", MSG, Budget(0.0001), client=client_with(lambda r: reply('{"a": 1}', cost=0), free))
    assert answer == {"a": 1}


def test_good_answer_and_request_shape():
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.read())
        return reply('{"a": 1}', cost=0.02)

    budget = Budget(0.1)
    data = chat_json("openai/gpt-4o-mini", MSG, budget, client=client_with(handler))
    assert data == {"a": 1}
    assert seen["auth"] == "Bearer sk-or-test-key"
    assert seen["body"]["model"] == "openai/gpt-4o-mini"
    assert seen["body"]["usage"] == {"include": True}
    assert budget.spent == pytest.approx(0.02)


def test_json_in_markdown_block():
    data = chat_json("m/m", MSG, Budget(1), client=client_with(lambda r: reply('```json\n{"a": 2}\n```')))
    assert data == {"a": 2}


def test_bad_json_is_retried_with_error_text():
    bodies = []
    answers = iter(["не json вообще", '{"ok": true}'])

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.read()))
        return reply(next(answers))

    assert chat_json("m/m", MSG, Budget(1), client=client_with(handler)) == {"ok": True}
    assert len(bodies) == 2
    # модель видит свой плохой ответ и причину
    assert "не прошёл проверку" in bodies[1]["messages"][-1]["content"]
    assert bodies[1]["messages"][-2]["content"] == "не json вообще"


def test_validate_error_goes_back_to_model():
    answers = iter(['{"n": 1}', '{"n": 5}'])

    def validate(data: dict[str, Any]) -> int:
        if data["n"] < 3:
            raise ValueError("n слишком маленькое")
        return int(data["n"])

    result = chat_json("m/m", MSG, Budget(1), validate=validate, client=client_with(lambda r: reply(next(answers))))
    assert result == 5


def test_gives_up_after_retries():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return reply("мусор")

    with pytest.raises(LlmError) as e:
        chat_json("m/m", MSG, Budget(1), client=client_with(handler))
    assert len(calls) == settings.max_retries + 1
    assert "sk-or-test-key" not in e.value.message


def test_429_and_5xx_are_retried():
    codes = iter([429, 503])

    def handler(request: httpx.Request) -> httpx.Response:
        code = next(codes, 200)
        return httpx.Response(code) if code != 200 else reply('{"a": 1}')

    assert chat_json("m/m", MSG, Budget(1), client=client_with(handler)) == {"a": 1}


def test_network_error_does_not_leak_key():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom " + request.headers["authorization"])

    with pytest.raises(LlmError) as e:
        chat_json("m/m", MSG, Budget(1), client=client_with(handler))
    assert "sk-or-test-key" not in e.value.message
    assert "ConnectError" in e.value.message


def test_error_text_from_openrouter_hides_key():
    def handler(request: httpx.Request) -> httpx.Response:
        echoed = "bad request with " + request.headers["authorization"]
        return httpx.Response(400, json={"error": {"message": echoed}})

    with pytest.raises(LlmError) as e:
        chat_json("m/m", MSG, Budget(1), client=client_with(handler))
    assert "sk-or-test-key" not in e.value.message
    assert "***" in e.value.message


def test_key_never_reaches_logs(caplog: pytest.LogCaptureFixture):
    #прогоняем всё: 429, сеть, битый json, ключ в тексте ошибки
    answers = iter(["429", "net", "garbage", '{"a": 1}'])

    def handler(request: httpx.Request) -> httpx.Response:
        step = next(answers)
        if step == "429":
            return httpx.Response(429, text="slow down " + request.headers["authorization"])
        if step == "net":
            raise httpx.ConnectError("boom " + request.headers["authorization"])
        return reply("не json" if step == "garbage" else step)

    caplog.set_level("DEBUG")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "max_retries", 3)
        assert chat_json("m/m", MSG, Budget(1), client=client_with(handler)) == {"a": 1}

    def echo(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": request.headers["authorization"]}})

    with pytest.raises(LlmError):
        chat_json("m/m", MSG, Budget(1), client=client_with(echo))
    assert caplog.records
    assert "sk-or-test-key" not in caplog.text


@pytest.mark.parametrize(
    ("code", "text"),
    [(401, "не принял ключ"), (403, "не принял ключ"), (402, "не хватает денег"), (400, "400")],
)
def test_client_errors_are_not_retried(code: int, text: str):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(code, json={"error": {"message": "плохо"}})

    with pytest.raises(LlmError) as e:
        chat_json("m/m", MSG, Budget(1), client=client_with(handler))
    assert text in e.value.message
    assert len(calls) == 1


def test_weird_response_format_is_retried():
    answers = iter([httpx.Response(200, json={"oops": 1}), reply('{"a": 1}')])
    assert chat_json("m/m", MSG, Budget(1), client=client_with(lambda r: next(answers))) == {"a": 1}


def test_cost_limit_stops_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return reply("мусор", cost=0.2)

    budget = Budget(0.1)
    with pytest.raises(CostLimit):
        chat_json("m/m", MSG, budget, client=client_with(handler))
    # после первого дорогого ответа больше не платим
    assert budget.spent == pytest.approx(0.2)


def test_unknown_cost_is_marked():
    budget = Budget(1)
    chat_json("m/m", MSG, budget, client=client_with(lambda r: reply('{"a": 1}', cost=None)))
    assert budget.known is False


def test_no_key_on_server(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr(""))
    with pytest.raises(LlmError):
        chat_json("m/m", MSG, Budget(1))


@pytest.mark.parametrize("text", ["", "нет скобок", "{не json}", "[1, 2]"])
def test_extract_json_rejects_garbage(text: str):
    with pytest.raises(ValueError):
        extract_json(text)


def test_key_is_hidden_in_settings_repr():
    assert "sk-or-test-key" not in repr(settings)
