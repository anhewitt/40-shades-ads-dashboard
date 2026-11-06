"""Import Amazon Sponsored Products results into the 40 Shades public dashboard.

The Windsor API key is provided ONLY by the GitHub Actions secret.
Do not publish this credential. Successful runs overwrite site/data.json.
Failed runs leave the prior snapshot unchanged.
"""
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

KEY = os.getenv("WINDSOR_API_KEY")
if not KEY:
    sys.exit("WINDSOR_API_KEY is not configured")
ACCOUNT = "1463085418545606"
START = "2026-10-30"
P = "sponsored_products_advertised_product__"
T = "sponsored_products_search_term__"
BOOKS = {
    "Teaching Hell": {"adgroup": "Teaching Hell - UK - Auto Test", "asin": "B0HQGTHJ6G"},
    "Corporate Misery": {"adgroup": "Corporate Misery - UK - Auto Test", "asin": "B0HPGVQGFK"},
}
FALLBACK = {refs["adgroup"]: name for name, refs in BOOKS.items()}

def num(value):
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None

def pull(fields):
    params = {
        "api_key": KEY,
        "fields": ",".join(fields),
        "date_from": START,
        "date_to": datetime.now(timezone.utc).date().isoformat(),
        "select_accounts": ACCOUNT,
    }
    url = "https://connectors.windsor.ai/amazon_ads?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "40ShadesAdsDashboard/2.0", "Accept": "application/json"})
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=80) as response:
                result = json.load(response)
            if isinstance(result, dict):
                if result.get("error"):
                    raise RuntimeError("Windsor error: " + str(result["error"])[:300])
                result = result.get("data", result.get("result", result.get("rows", [])))
            if not isinstance(result, list):
                raise RuntimeError("Unexpected Windsor API response")
            return result
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            print(f"Windsor attempt {attempt}/3 timed out or failed: {type(exc).__name__}", flush=True)
            if attempt == 3:
                raise RuntimeError("Windsor did not respond after three attempts") from exc
            time.sleep(attempt * 4)

def campaign_name(row):
    adgroup = str(row.get(P + "ad_group_name") or "")
    asin = str(row.get(P + "advertised_asin") or "").upper()
    campaign = str(row.get(P + "campaign_name") or "")
    for name, refs in BOOKS.items():
        if adgroup == refs["adgroup"] or asin == refs["asin"]:
            return name
    return FALLBACK.get(campaign)

def aggregate_rows(rows, prefix, metrics, identity):
    """Aggregate several source rows per day and key, retaining unknown as None."""
    sums = defaultdict(lambda: {m: None for m in metrics})
    for row in rows:
        key = identity(row)
        date = str(row.get("date") or "")[:10]
        if not key or not date:
            continue
        entry = sums[(key, date)]
        for output_key, source_key in metrics.items():
            value = num(row.get(prefix + source_key))
            if value is not None:
                entry[output_key] = (entry[output_key] or 0) + value
    return sums

def main():
    fields = ["date", P + "ad_group_name", P + "advertised_asin", P + "campaign_name",
              P + "impressions", P + "clicks", P + "cost", P + "sales_14d",
              P + "purchases_14d", P + "units_sold_clicks_14d"]
    campaign_rows = pull(fields)
    metrics = {"impressions": "impressions", "clicks": "clicks", "spend": "cost",
               "sales": "sales_14d", "orders": "purchases_14d",
               "units": "units_sold_clicks_14d"}
    grouped = aggregate_rows(campaign_rows, P, metrics, campaign_name)
    if not grouped:
        raise RuntimeError("No date-stamped advertised-product records matched either title")
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Windsor.ai / UK Amazon Sponsored Products",
        "royalty_per_copy_gbp": 2.64,
        "royalty_is_estimate": True,
        "campaigns": {book: [] for book in BOOKS},
        "search_terms": {book: [] for book in BOOKS},
        "search_term_date_filtered": False,
        "partial": False,
    }
    for (book, date), totals in grouped.items():
        data["campaigns"][book].append({"date": date, **totals})
    for values in data["campaigns"].values():
        values.sort(key=lambda row: row["date"])
    print("Product rows:", {key: len(value) for key, value in data["campaigns"].items()}, flush=True)

    # Search terms are supplementary: if the report is slow, keep primary figures.
    try:
        term_fields = ["date", T + "ad_group_name", T + "campaign_name", T + "search_term",
                       T + "clicks", T + "cost", T + "sales_14d", T + "units_sold_clicks_14d"]
        term_rows = pull(term_fields)
        term_metrics = {"clicks": "clicks", "spend": "cost",
                        "sales": "sales_14d", "units": "units_sold_clicks_14d"}
        def term_identity(row):
            group = str(row.get(T + "ad_group_name") or "")
            name = next((b for b, refs in BOOKS.items() if group == refs["adgroup"]), None)
            name = name or FALLBACK.get(str(row.get(T + "campaign_name") or ""))
            term = str(row.get(T + "search_term") or "").strip()
            return (name, term) if name and term else None
        terms = aggregate_rows(term_rows, T, term_metrics, term_identity)
        for ((book, term), date), values in terms.items():
            data["search_terms"][book].append({"date": date, "term": term, **values})
        data["search_term_date_filtered"] = bool(terms)
        for values in data["search_terms"].values():
            values.sort(key=lambda row: (row["date"], row["term"]))
        if not terms:
            data["partial"] = True
            print("Search terms returned no dated rows; do not show lifetime terms as time-filtered", flush=True)
    except Exception as exc:
        data["partial"] = True
        print("Search terms unavailable; primary metrics retained:", str(exc)[:180], flush=True)

    target = Path(__file__).parent / "site" / "data.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    print("Published data snapshot updated:", data["generated_at"], flush=True)

if __name__ == "__main__":
    main()
