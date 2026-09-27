import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.field_support import app  # noqa: E402


def main() -> None:
    if "INFRAI_API_KEY" not in os.environ:
        raise SystemExit("Set INFRAI_API_KEY before running the demo")

    work_order_id = f"demo-{uuid4().hex}"
    update = {
        "update_id": f"update-{work_order_id}-photo-1",
        "work_order_id": work_order_id,
        "customer_id": "customer-88",
        "dispatch_status": "on_site",
        "message": "Is this valve the source of the leak?",
        "photo_urls": ["https://media.example.test/work-orders/1042/valve.jpg"],
        "technician_replied": False,
    }
    with TestClient(app) as client:
        session = client.post(
            "/support/sessions",
            json={"work_order_id": work_order_id, "customer_id": update["customer_id"]},
        )
        if not session.is_success:
            print(json.dumps(session.json(), indent=2), file=sys.stderr)
            raise SystemExit(1)
        response = client.post("/support/updates", json=update)
    if not response.is_success:
        print(json.dumps(response.json(), indent=2), file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(response.json(), indent=2))


if __name__ == "__main__":
    main()
