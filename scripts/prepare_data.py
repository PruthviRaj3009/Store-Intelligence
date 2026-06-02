"""
prepare_data.py — Normalize the raw Purplle POS export into the simple
transaction-level schema the Intelligence API consumes, and derive a staff roster.

The challenge's idealized spec described a clean POS file:
    store_id, transaction_id, timestamp, basket_value_inr
The real export (Brigade_Bangalore_10_April_26.csv) is line-item level with 39
columns. We collapse it to one row per invoice (a "transaction") and convert the
local (Asia/Kolkata) order date+time to ISO-8601 UTC, which is what events use.

We also emit staff_roster.json from the distinct salespeople — those employee
codes are known store staff and feed the detection pipeline's staff-exclusion
narrative (see CHOICES.md).

Run:  python scripts/prepare_data.py
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))

ROOT = Path(__file__).resolve().parents[1]
RAW_CSV = ROOT / "data" / "raw" / "pos_raw.csv"
OUT_CSV = ROOT / "data" / "pos_transactions.csv"
OUT_STAFF = ROOT / "data" / "staff_roster.json"

STORE_ID = "ST1008"


def parse_ts(order_date: str, order_time: str) -> str:
    """'10-04-2026' + '16:55:36' (IST) -> ISO-8601 UTC, e.g. 2026-04-10T11:25:36Z."""
    dt_local = datetime.strptime(f"{order_date} {order_time}", "%d-%m-%Y %H:%M:%S")
    dt_local = dt_local.replace(tzinfo=IST)
    return dt_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_float(x: str) -> float:
    try:
        return round(float(x), 2)
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    rows = list(csv.DictReader(open(RAW_CSV, encoding="utf-8-sig")))

    # --- collapse line items -> one transaction per invoice ---
    invoices: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        invoices[r["invoice_number"]].append(r)

    txns = []
    for invoice, items in invoices.items():
        head = items[0]
        basket = round(sum(to_float(i["total_amount"]) for i in items), 2)
        txns.append(
            {
                "store_id": STORE_ID,
                "transaction_id": invoice,
                "timestamp": parse_ts(head["order_date"], head["order_time"]),
                "basket_value_inr": basket,
                "line_items": len(items),
            }
        )
    txns.sort(key=lambda t: t["timestamp"])

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["store_id", "transaction_id", "timestamp", "basket_value_inr", "line_items"],
        )
        w.writeheader()
        w.writerows(txns)

    # --- staff roster from distinct salespeople ---
    staff = {}
    for r in rows:
        name = (r.get("salesperson_name") or "").strip()
        code = (r.get("employee_code") or "").strip()
        if code and name:
            staff[code] = name
    roster = {
        "store_id": STORE_ID,
        "_note": "Known store staff derived from POS salesperson records. Used by the "
                 "detection pipeline as ground-truth that N staff are present, to "
                 "calibrate the staff-exclusion heuristic (see pipeline/staff.py).",
        "staff": [{"employee_code": c, "name": n} for c, n in sorted(staff.items())],
        "staff_count": len(staff),
    }
    OUT_STAFF.write_text(json.dumps(roster, indent=2), encoding="utf-8")

    print(f"[prepare_data] {len(rows)} line items -> {len(txns)} transactions -> {OUT_CSV}")
    print(f"[prepare_data] basket range: "
          f"{min(t['basket_value_inr'] for t in txns)} .. {max(t['basket_value_inr'] for t in txns)}")
    print(f"[prepare_data] time range (UTC): {txns[0]['timestamp']} .. {txns[-1]['timestamp']}")
    print(f"[prepare_data] staff roster: {roster['staff_count']} -> {OUT_STAFF}")


if __name__ == "__main__":
    main()
