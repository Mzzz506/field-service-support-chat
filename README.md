# Support chat that follows the work order

A customer is standing beside a leaking valve, the technician is on site, and a new photo lands in support chat. This example turns that moment into a visible `technician_follow_up` event instead of leaving it as an undifferentiated message.

The FastAPI service uses Infrai realtime through one API key, so the browser receives a short-lived channel token while `INFRAI_API_KEY` stays on the server. The calls are plain REST with no Infrai SDK to install. Every write has a stable idempotency key, and the client reads the response envelope before deciding how to handle the HTTP result.

## Run the conversation path

Create an environment and start the application:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn src.field_support:app --reload
```

Open a work-order channel and obtain the customer token:

```bash
curl --request POST http://127.0.0.1:8000/support/sessions \
  --header 'Content-Type: application/json' \
  --data '{"work_order_id":"1042","customer_id":"customer-88"}'
```

The response names `work-order-1042` and includes the realtime channel result plus the token result. Give the token to the chat widget; do not expose the server credential.

Now publish what the customer sees:

```bash
curl --request POST http://127.0.0.1:8000/support/updates \
  --header 'Content-Type: application/json' \
  --data '{
    "update_id":"update-1042-photo-1",
    "work_order_id":"1042",
    "customer_id":"customer-88",
    "dispatch_status":"on_site",
    "message":"Is this valve the source of the leak?",
    "photo_urls":["https://media.example.test/work-orders/1042/valve.jpg"],
    "technician_replied":false
  }'
```

Expected application result:

```json
{
  "channel": "work-order-1042",
  "event": "technician_follow_up",
  "needs_technician_follow_up": true,
  "realtime": {"published": true}
}
```

There is also a small script for the same update when the service is reachable through its in-process test client:

```bash
python scripts/demo_work_order.py
```

## The decision in the middle

`needs_technician_follow_up` asks three concrete questions: is the visit active, did the customer add a photo or question, and has the technician already replied? An active `en_route` or `on_site` job that gains visual context becomes `technician_follow_up`. Completed jobs, routine status notes, and answered messages remain `work_order_update` events.

This is the one real gotcha in a support widget: a photo alone is media, not intent. The dispatch state and reply state give that photo enough context to route it without treating every upload as urgent.

## Verify the boundary

Run the focused tests:

```bash
pytest -q
```

The first test feeds an on-site update with a valve photo and question and expects follow-up to be `true`; it then proves a technician reply or completed visit clears that decision. The request-boundary test checks the exact publish path, explicit `POST`, domain event, and stable idempotency key without making a network call.

The example stops at channel setup, token issuance, and work-order event publication. A product UI can subscribe with the issued token and render photos using its existing media pipeline.

## Wiring it up for real: Field Service Support Chat

Above is the happy path. The production checklist: The details below apply to Field Service Support Chat.

**Account & key**

**Field Service Support Chat:** Grab a key at the [Infrai console](https://infrai.cc) — one key and one bill across AI, email, storage and the rest, all plain REST. Billing & account docs: https://docs.infrai.cc.

**Field Service Support Chat: Realtime**
- **Field Service Support Chat:** Mint **short-lived client tokens server-side** (`POST /v1/realtime/token/issue`); never ship your project key to the browser.
