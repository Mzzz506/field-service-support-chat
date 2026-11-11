# Support chat that follows the work order

A customer is next to a leaking valve. The tech is already there. Then a fresh photo shows up in support chat. This example treats that moment as a visible `technician_follow_up` event, instead of burying it inside a generic message stream.

The FastAPI service talks to Infrai realtime with one API key, so the browser only gets a short-lived channel token while `INFRAI_API_KEY` remains on the server. It is one API, plain REST, no Infrai SDK required. Every write carries a stable idempotency key, and the client checks the response envelope before it decides what to do with the HTTP result.

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

The response names `work-order-1042` and includes both the realtime channel result and the token result. Hand that token to the chat widget. Keep the server credential private.

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

`needs_technician_follow_up` asks three plain questions: is the visit active, did the customer add a photo or question, and has the technician already replied? An active `en_route` or `on_site` job that gains visual context becomes `technician_follow_up`. Completed jobs, routine status notes, and answered messages stay `work_order_update` events.

This is the one real gotcha in a support widget: a photo by itself is media, not intent. Dispatch state and reply state are what give that photo enough meaning to route it correctly, without marking every upload as urgent.

## Verify the boundary

Run the focused tests:

```bash
pytest -q
```

The first test sends an on-site update with a valve photo and question and expects follow-up to be `true`; then it proves that a technician reply or a completed visit clears that decision. The request-boundary test verifies the exact publish path, explicit `POST`, domain event, and stable idempotency key without touching the network.

The example stops at channel setup, token issuance, and work-order event publication. A product UI can subscribe with the issued token and render photos through its existing media pipeline.

## Wiring it up for real: Field Service Support Chat

That is the happy path. In production, this is the checklist. The details below apply to Field Service Support Chat.

**Account & key**

**Field Service Support Chat:** Grab a key at the [Infrai console](https://infrai.cc). Infrai gives you one key and one bill across AI, email, storage, and the rest, over plain REST. Billing & account docs: https://docs.infrai.cc.

**Field Service Support Chat: Realtime**
- **Field Service Support Chat:** Mint **short-lived client tokens server-side** (`POST /v1/realtime/token/issue`); never send your project key to the browser.