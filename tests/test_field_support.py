import json

import httpx
import pytest

from scripts import demo_work_order
from src.field_support import InfraiRealtime, WorkOrderUpdate, needs_technician_follow_up


def make_update(**changes: object) -> WorkOrderUpdate:
    values = {
        "update_id": "update-1042-photo-1",
        "work_order_id": "1042",
        "customer_id": "customer-88",
        "dispatch_status": "on_site",
        "message": "Is this valve the source of the leak?",
        "photo_urls": ["https://media.example.test/work-orders/1042/valve.jpg"],
        "technician_replied": False,
    }
    values.update(changes)
    return WorkOrderUpdate.model_validate(values)


def test_photo_question_during_visit_requests_technician_follow_up() -> None:
    assert needs_technician_follow_up(make_update()) is True
    assert needs_technician_follow_up(make_update(technician_replied=True)) is False
    assert needs_technician_follow_up(make_update(dispatch_status="completed")) is False


@pytest.mark.asyncio
async def test_channel_creation_uses_private_type() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "data": {"channel": "work-order-test"}})

    realtime = InfraiRealtime(api_key="test-key", transport=httpx.MockTransport(handler))
    await realtime.create_channel("work-order-test")
    assert captured == [{"channel": "work-order-test", "type": "private"}]


@pytest.mark.asyncio
async def test_publish_uses_domain_event_and_idempotency_key() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True, "data": {"published": True}})

    realtime = InfraiRealtime(api_key="test-key", transport=httpx.MockTransport(handler))
    update = make_update()
    event = "technician_follow_up" if needs_technician_follow_up(update) else "work_order_update"
    result = await realtime.publish(
        "work-order-1042",
        event,
        {"dispatch_status": update.dispatch_status, "photo_urls": update.photo_urls},
        update.customer_id,
        update.update_id,
    )

    assert result == {"published": True}
    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/realtime/publish"
    assert captured["headers"]["idempotency-key"] == "event:update-1042-photo-1"
    assert '"event":"technician_follow_up"' in str(captured["body"]).replace(" ", "")


@pytest.mark.parametrize("failed_step", [None, "session", "publish"])
def test_demo_creates_session_before_publish_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch, failed_step: str | None
) -> None:
    calls: list[str] = []

    class Client:
        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(self, path: str, json: object) -> httpx.Response:
            step = "session" if path == "/support/sessions" else "publish"
            calls.append(step)
            return httpx.Response(
                400 if step == failed_step else 200,
                json={"detail": "failed"} if step == failed_step else {"ok": True},
            )

    monkeypatch.setenv("INFRAI_API_KEY", "test-key")
    monkeypatch.setattr(demo_work_order, "TestClient", lambda _: Client())
    if failed_step:
        with pytest.raises(SystemExit) as exc:
            demo_work_order.main()
        assert exc.value.code == 1
    else:
        demo_work_order.main()
    assert calls == (["session"] if failed_step == "session" else ["session", "publish"])
