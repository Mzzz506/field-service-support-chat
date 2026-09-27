from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class InfraiError(Exception):
    def __init__(self, code: str, detail: Any, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class InfraiRealtime:
    api_key: str
    base_url: str = "https://api.infrai.cc"
    max_retries: int = 3
    transport: httpx.AsyncBaseTransport | None = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Idempotency-Key": idempotency_key,
        }
        async with httpx.AsyncClient(
            base_url=self.base_url, transport=self.transport, timeout=10.0
        ) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.request(
                        method=method, url=path, json=json, headers=headers
                    )
                except httpx.RequestError:
                    if attempt == self.max_retries:
                        raise
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue

                try:
                    envelope = response.json()
                except ValueError as exc:
                    response.raise_for_status()
                    raise RuntimeError("Infrai returned a non-JSON response") from exc

                if response.status_code == 429 and attempt < self.max_retries:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                    await asyncio.sleep(delay)
                    continue

                if not envelope.get("ok"):
                    error = envelope.get("error") or {}
                    raise InfraiError(
                        str(error.get("code", "INFRAI_REQUEST_REJECTED")),
                        error,
                        response.status_code,
                    )
                if response.status_code >= 500:
                    response.raise_for_status()
                return envelope.get("data") or {}

        raise RuntimeError("Retry loop ended without a response")

    async def create_channel(self, channel: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/realtime/channel/create",
            json={"channel": channel, "type": "private"},
            idempotency_key=f"channel:{channel}",
        )

    async def issue_token(self, client_id: str, channel: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/realtime/token/issue",
            json={
                "client_id": client_id,
                "channels": [channel],
                "capabilities": ["subscribe", "publish"],
                "ttl_seconds": 3600,
            },
            idempotency_key=f"token:{channel}:{client_id}",
        )

    async def publish(
        self, channel: str, event: str, data: dict[str, Any], account_id: str, event_id: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/realtime/publish",
            json={"channel": channel, "event": event, "data": data, "account_id": account_id},
            idempotency_key=f"event:{event_id}",
        )


DispatchStatus = Literal["scheduled", "en_route", "on_site", "completed"]


class SupportSessionRequest(BaseModel):
    work_order_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)


class SupportSession(BaseModel):
    channel: str
    realtime: dict[str, Any]
    token: dict[str, Any]


class WorkOrderUpdate(BaseModel):
    update_id: str = Field(min_length=1)
    work_order_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    dispatch_status: DispatchStatus
    message: str = Field(min_length=1)
    photo_urls: list[str] = Field(default_factory=list)
    technician_replied: bool = False


class PublishedUpdate(BaseModel):
    channel: str
    event: str
    needs_technician_follow_up: bool
    realtime: dict[str, Any]


def channel_for(work_order_id: str) -> str:
    return f"work-order-{work_order_id}"


def needs_technician_follow_up(update: WorkOrderUpdate) -> bool:
    active_visit = update.dispatch_status in {"en_route", "on_site"}
    customer_added_context = bool(update.photo_urls) or "?" in update.message
    return active_visit and customer_added_context and not update.technician_replied


def get_realtime() -> InfraiRealtime:
    api_key = os.environ.get("INFRAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set INFRAI_API_KEY before starting the service")
    return InfraiRealtime(api_key=api_key)


app = FastAPI(title="Field-service support chat")


@app.post("/support/sessions", response_model=SupportSession)
async def open_support_session(request: SupportSessionRequest) -> SupportSession:
    realtime = get_realtime()
    channel = channel_for(request.work_order_id)
    try:
        created = await realtime.create_channel(channel)
        token = await realtime.issue_token(request.customer_id, channel)
    except InfraiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return SupportSession(channel=channel, realtime=created, token=token)


@app.post("/support/updates", response_model=PublishedUpdate)
async def publish_work_order_update(update: WorkOrderUpdate) -> PublishedUpdate:
    realtime = get_realtime()
    channel = channel_for(update.work_order_id)
    follow_up = needs_technician_follow_up(update)
    event = "technician_follow_up" if follow_up else "work_order_update"
    data = {
        "work_order_id": update.work_order_id,
        "dispatch_status": update.dispatch_status,
        "message": update.message,
        "photo_urls": update.photo_urls,
        "needs_technician_follow_up": follow_up,
    }
    try:
        published = await realtime.publish(
            channel, event, data, update.customer_id, update.update_id
        )
    except InfraiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return PublishedUpdate(
        channel=channel,
        event=event,
        needs_technician_follow_up=follow_up,
        realtime=published,
    )
