"""
Monday.com API client for Skylark Drones BI Agent.
Tools return compact SUMMARIES + a small sample of records — not all raw data.
This keeps token usage low and answers fast.
"""

import json
import time
import requests
from collections import Counter, defaultdict
from config import (
    MONDAY_API_KEY,
    DEALS_BOARD_ID,
    WORK_ORDERS_BOARD_ID,
    DEALS_COLUMNS,
    WORK_ORDERS_COLUMNS,
)

MONDAY_API_URL = "https://api.monday.com/v2"

# ── In-memory cache (5-minute TTL) ───────────────────────────────────────────
_cache: dict = {}
_cache_time: dict = {}
CACHE_TTL = 300  # seconds


def _monday_query(query: str) -> dict:
    headers = {
        "Authorization": MONDAY_API_KEY,
        "Content-Type": "application/json",
        "API-Version": "2024-01",
    }
    resp = requests.post(MONDAY_API_URL, headers=headers, json={"query": query}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Monday.com API error: {data['errors']}")
    return data


def _parse_numeric(val) -> float | None:
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _fetch_board_items(board_id: str, col_map: dict, name_key: str) -> list[dict]:
    cache_key = f"board_{board_id}"
    now = time.time()
    if cache_key in _cache and (now - _cache_time.get(cache_key, 0)) < CACHE_TTL:
        return _cache[cache_key]

    id_to_title = {v: k for k, v in col_map.items()}
    all_items: list[dict] = []
    cursor = None

    while True:
        if cursor:
            gql = f"""
            {{
                next_items_page(limit: 500, cursor: "{cursor}") {{
                    cursor
                    items {{ id name column_values {{ id text }} }}
                }}
            }}"""
        else:
            gql = f"""
            {{
                boards(ids: [{board_id}]) {{
                    items_page(limit: 500) {{
                        cursor
                        items {{ id name column_values {{ id text }} }}
                    }}
                }}
            }}"""

        result = _monday_query(gql)
        page = result["data"]["next_items_page"] if cursor else result["data"]["boards"][0]["items_page"]
        items = page.get("items", [])
        cursor = page.get("cursor")

        for item in items:
            record: dict = {name_key: item["name"]}
            for cv in item["column_values"]:
                title = id_to_title.get(cv["id"])
                if title and title != name_key:
                    record[title] = cv.get("text") or None
            all_items.append(record)

        if not cursor or not items:
            break

    _cache[cache_key] = all_items
    _cache_time[cache_key] = now
    return all_items


def _fetch_all_deals() -> list[dict]:
    return _fetch_board_items(DEALS_BOARD_ID, DEALS_COLUMNS, "Deal Name")


def _fetch_all_work_orders() -> list[dict]:
    return _fetch_board_items(WORK_ORDERS_BOARD_ID, WORK_ORDERS_COLUMNS, "Deal name masked")


def _ifilter(records, key, value):
    v = value.strip().lower()
    return [r for r in records if r.get(key) and r[key].strip().lower() == v]


def _summarize_deals(records: list[dict]) -> dict:
    """Build a compact summary dict from a list of deal records."""
    n = len(records)
    values = [_parse_numeric(r.get("Masked Deal value")) for r in records]
    valid_vals = [v for v in values if v is not None]

    # Closure probability and deal stage are only meaningful for Open deals
    open_records = [r for r in records if (r.get("Deal Status") or "").strip().lower() == "open"]

    return {
        "total_records": n,
        "records_with_value": len(valid_vals),
        "records_without_value": n - len(valid_vals),
        "total_deal_value_inr": round(sum(valid_vals), 2) if valid_vals else None,
        "by_deal_status": dict(Counter(r.get("Deal Status") or "Unknown" for r in records)),
        "by_sector": dict(Counter(r.get("Sector") or "Unknown" for r in records)),
        "open_deals_count": len(open_records),
        "by_closure_probability_open_only": dict(Counter(r.get("Closure Probability") or "Not Set" for r in open_records)),
        "by_deal_stage_open_only": dict(Counter(r.get("Deal Stage") or "Unknown" for r in open_records)),
        "by_product": dict(Counter(r.get("Product deal") or "Not Specified" for r in records)),
        "by_owner": dict(Counter(r.get("Owner code") or "Unknown" for r in records)),
        "sample_records": [
            {k: v for k, v in r.items() if k in [
                "Deal Name", "Deal Status", "Deal Stage", "Sector",
                "Closure Probability", "Masked Deal value", "Tentative Close Date",
                "Owner code", "Client Code", "Product deal"
            ]}
            for r in records[:8]
        ],
    }


def _summarize_work_orders(records: list[dict]) -> dict:
    """Build a compact summary dict from a list of work order records."""
    n = len(records)

    def _sum_col(key):
        vals = [_parse_numeric(r.get(key)) for r in records]
        valid = [v for v in vals if v is not None]
        return round(sum(valid), 2), len(vals) - len(valid)

    contract_val, c1 = _sum_col("Amount in Rupees (Excl of GST) (Masked)")
    billed_val, c2 = _sum_col("Billed Value in Rupees (Excl of GST.) (Masked)")
    collected_val, c3 = _sum_col("Collected Amount in Rupees (Incl of GST.) (Masked)")
    receivable_val, c4 = _sum_col("Amount Receivable (Masked)")
    to_bill_val, c5 = _sum_col("Amount to be billed in Rs. (Exl. of GST) (Masked)")

    return {
        "total_records": n,
        "by_execution_status": dict(Counter(r.get("Execution Status") or "Unknown" for r in records)),
        "by_sector": dict(Counter(r.get("Sector") or "Unknown" for r in records)),
        "by_nature_of_work": dict(Counter(r.get("Nature of Work") or "Unknown" for r in records)),
        "by_invoice_status": dict(Counter(r.get("Invoice Status") or "Unknown" for r in records)),
        "by_wo_status": dict(Counter(r.get("WO Status (billed)") or "Unknown" for r in records)),
        "by_billing_status": dict(Counter(r.get("Billing Status") or "Unknown" for r in records)),
        "financials_excl_gst": {
            "total_contract_value_inr": contract_val,
            "total_billed_inr": billed_val,
            "total_to_bill_inr": to_bill_val,
            "total_receivable_inr": receivable_val,
            "total_collected_incl_gst_inr": collected_val,
        },
        "null_counts": {
            "contract_value": c1, "billed_value": c2,
            "collected": c3, "receivable": c4, "to_bill": c5,
        },
        "sample_records": [
            {k: v for k, v in r.items() if k in [
                "Deal name masked", "Serial #", "Execution Status", "Sector",
                "Nature of Work", "Invoice Status", "Billing Status",
                "Amount in Rupees (Excl of GST) (Masked)",
                "Billed Value in Rupees (Excl of GST.) (Masked)",
                "Amount Receivable (Masked)", "Date of PO/LOI"
            ]}
            for r in records[:8]
        ],
    }


# ── Tool Functions ────────────────────────────────────────────────────────────

def fetch_deals(
    sector: str = None,
    deal_status: str = None,
    deal_stage: str = None,
    closure_probability: str = None,
    owner_code: str = None,
    limit: int = None,
) -> str:
    """
    Fetch and summarize deals from the Skylark Drones Deals board on Monday.com.

    Use for: pipeline health, deal stages, win/loss rates, sector deal counts,
    closure probability, deal values, owner performance.

    Args:
        sector: Filter by sector. Options: Mining, Renewables, Railways, Powerline, Construction, Others
        deal_status: Filter by status. Options: Open, Won, Dead, On Hold
        deal_stage: Filter by stage (partial match). Example: "F. Negotiations"
        closure_probability: Options: High, Medium, Low
        owner_code: Salesperson code. Example: OWNER_001
        limit: Max sample records to show (does not affect aggregates)

    Returns:
        JSON with aggregated summary + up to 8 sample records.
    """
    records = _fetch_all_deals()
    board_total = len(records)

    if sector:
        records = _ifilter(records, "Sector", sector)
    if deal_status:
        records = _ifilter(records, "Deal Status", deal_status)
    if deal_stage:
        records = [r for r in records if r.get("Deal Stage") and deal_stage.lower() in r["Deal Stage"].lower()]
    if closure_probability:
        records = _ifilter(records, "Closure Probability", closure_probability)
    if owner_code:
        records = _ifilter(records, "Owner code", owner_code)

    summary = _summarize_deals(records)
    summary["board_total"] = board_total
    summary["filters_applied"] = {
        k: v for k, v in {
            "sector": sector, "deal_status": deal_status, "deal_stage": deal_stage,
            "closure_probability": closure_probability, "owner_code": owner_code,
        }.items() if v
    }
    return json.dumps(summary)


def fetch_work_orders(
    sector: str = None,
    execution_status: str = None,
    nature_of_work: str = None,
    invoice_status: str = None,
    wo_status: str = None,
    limit: int = None,
) -> str:
    """
    Fetch and summarize work orders from the Skylark Drones Work Orders board on Monday.com.

    Use for: project execution status, billing, revenue, collections,
    receivables, invoice status, operational metrics.

    Args:
        sector: Filter by sector. Options: Mining, Renewables, Railways, Powerline, Construction, Others
        execution_status: Options: Completed, Ongoing, Not Started, Paused, Partially Completed
        nature_of_work: Options: One Time Project, Monthly Contract, Annual Rate Contract, Proof of Concept
        invoice_status: Options: Fully Billed, Partially Billed, Not Billed, Stuck
        wo_status: Options: Closed, Open
        limit: Max sample records (does not affect aggregates)

    Returns:
        JSON with aggregated financial summary + up to 8 sample records.
    """
    records = _fetch_all_work_orders()
    board_total = len(records)

    if sector:
        records = _ifilter(records, "Sector", sector)
    if execution_status:
        records = _ifilter(records, "Execution Status", execution_status)
    if nature_of_work:
        records = _ifilter(records, "Nature of Work", nature_of_work)
    if invoice_status:
        records = _ifilter(records, "Invoice Status", invoice_status)
    if wo_status:
        records = _ifilter(records, "WO Status (billed)", wo_status)

    summary = _summarize_work_orders(records)
    summary["board_total"] = board_total
    summary["filters_applied"] = {
        k: v for k, v in {
            "sector": sector, "execution_status": execution_status,
            "nature_of_work": nature_of_work, "invoice_status": invoice_status,
            "wo_status": wo_status,
        }.items() if v
    }
    return json.dumps(summary)


def fetch_cross_board(
    sector: str = None,
    deal_status: str = None,
    execution_status: str = None,
) -> str:
    """
    Cross-board analysis joining Deals and Work Orders on deal name.

    Use for: overall business health, sector performance combining pipeline +
    execution, deals without work orders, conversion from won deals to execution.

    Note: 6 orphan WOs (Dolphin, GG Go, Golden Fish, Octopus, Turtle, Whale)
    have no matching deal and are excluded from the join.

    Args:
        sector: Filter both boards by sector.
        deal_status: Filter deals by status. Options: Open, Won, Dead, On Hold
        execution_status: Filter work orders. Options: Completed, Ongoing, Not Started, Paused, Partially Completed

    Returns:
        JSON with cross-board summary.
    """
    deals = _fetch_all_deals()
    work_orders = _fetch_all_work_orders()

    ORPHANS = {"dolphin", "gg go", "golden fish", "octopus", "turtle", "whale"}

    # Apply deal filters
    if sector:
        deals = _ifilter(deals, "Sector", sector)
    if deal_status:
        deals = _ifilter(deals, "Deal Status", deal_status)

    # Apply WO filters
    filtered_wos = work_orders
    if sector:
        filtered_wos = _ifilter(filtered_wos, "Sector", sector)
    if execution_status:
        filtered_wos = _ifilter(filtered_wos, "Execution Status", execution_status)

    # Build WO lookup
    wo_lookup = defaultdict(list)
    for w in filtered_wos:
        key = (w.get("Deal name masked") or "").strip().lower()
        if key not in ORPHANS:
            wo_lookup[key].append(w)

    deals_with_wo = []
    deals_without_wo = []
    for d in deals:
        key = (d.get("Deal Name") or "").strip().lower()
        wos = wo_lookup.get(key, [])
        if wos:
            deals_with_wo.append(d)
        else:
            deals_without_wo.append(d)

    deal_summary = _summarize_deals(deals)
    wo_summary = _summarize_work_orders(list({
        w["Serial #"]: w for wlist in wo_lookup.values() for w in wlist
        if w.get("Serial #")
    }.values()))

    return json.dumps({
        "deals_summary": deal_summary,
        "work_orders_summary": wo_summary,
        "cross_board": {
            "total_deals": len(deals),
            "deals_with_work_orders": len(deals_with_wo),
            "deals_without_work_orders": len(deals_without_wo),
            "sample_deals_without_wo": [
                d.get("Deal Name") for d in deals_without_wo[:10]
            ],
        },
        "filters_applied": {
            k: v for k, v in {
                "sector": sector, "deal_status": deal_status,
                "execution_status": execution_status,
            }.items() if v
        },
    })
