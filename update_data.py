"""Refresh public 40 Shades dashboard snapshot from Windsor.ai Amazon Ads.
API key is read only from GitHub Actions secret WINDSOR_API_KEY.
"""
import json, os, sys, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

KEY=os.environ.get("WINDSOR_API_KEY")
if not KEY:
    sys.exit("WINDSOR_API_KEY is not configured; skipping live data import")
ACCOUNT="1463085418545606"
START="2026-10-30"
P="sponsored_products_advertised_product__"
T="sponsored_products_search_term__"
BOOKS={
 "Teaching Hell":{"adgroup":"Teaching Hell - UK - Auto Test","asin":"B0HQGTHJ6G"},
 "Corporate Misery":{"adgroup":"Corporate Misery - UK - Auto Test","asin":"B0HPGVQGFK"},
}
CAMPAIGN_FALLBACK={"Teaching Hell - UK - Auto Test":"Teaching Hell",
 "Corporate Misery - UK - Auto Test":"Corporate Misery"}

def book_for(row,prefix):
    group=str(row.get(prefix+"ad_group_name") or "")
    asin=str(row.get(prefix+"advertised_asin") or "").upper()
    campaign=str(row.get(prefix+"campaign_name") or "")
    for title,refs in BOOKS.items():
        if group==refs["adgroup"] or asin==refs["asin"]:
            return title
    return CAMPAIGN_FALLBACK.get(campaign)

def pull(fields):
    query={"api_key":KEY,"fields":",".join(fields),"date_from":START,
           "date_to":datetime.now(timezone.utc).date().isoformat(),"select_accounts":ACCOUNT}
    url="https://connectors.windsor.ai/amazon_ads?"+urllib.parse.urlencode(query)
    req=urllib.request.Request(url,headers={"User-Agent":"40ShadesDashboard/1.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=150) as response:
        result=json.load(response)
    if isinstance(result,dict):
        if result.get("error"):raise RuntimeError(str(result["error"]))
        result=result.get("data",result.get("result",result.get("rows",[])))
    if not isinstance(result,list):raise RuntimeError("Unexpected Windsor.ai response format")
    return result

def num(v):
    try:return float(v) if v is not None and v!="" else None
    except (TypeError,ValueError):return None

output={"generated_at":datetime.now(timezone.utc).isoformat(),"source":"Windsor.ai Amazon Ads",
        "campaigns":{x:[] for x in BOOKS},"search_terms":{},"partial":False}
fields=["date",P+"ad_group_name",P+"advertised_asin",P+"campaign_name",
        P+"impressions",P+"clicks",P+"cost",P+"sales_14d",P+"purchases_14d"]
rows=pull(fields)
seen=set()
for r in rows:
    name=book_for(r,P)
    if not name:continue
    date=str(r.get("date",""))[:10]
    if not date:continue
    seen.add(name)
    output["campaigns"][name].append({"date":date,
        "impressions":num(r.get(P+"impressions")),
        "clicks":num(r.get(P+"clicks")),
        "spend":num(r.get(P+"cost")),
        "sales":num(r.get(P+"sales_14d")),
        "orders":num(r.get(P+"purchases_14d"))})
for days in output["campaigns"].values():
    days.sort(key=lambda r:r["date"])
if not seen:
    raise RuntimeError("Windsor.ai returned no matching advertised products; check account and data availability")
try:
    search=pull([T+"campaign_name",T+"ad_group_name",T+"search_term",T+"clicks",T+"cost",T+"sales_14d"])
    for title,refs in BOOKS.items():
        output["search_terms"][title]=sorted(
            [{"term":str(r.get(T+"search_term") or ""),"clicks":num(r.get(T+"clicks")),
              "spend":num(r.get(T+"cost")),"sales":num(r.get(T+"sales_14d"))}
             for r in search if (r.get(T+"ad_group_name")==refs["adgroup"]
                or CAMPAIGN_FALLBACK.get(r.get(T+"campaign_name"))==title)
                and r.get(T+"search_term")],
            key=lambda x:x["spend"] or 0,reverse=True)[:15]
except Exception as exc:
    output["partial"]=True
    print("Search-term query unavailable:",str(exc)[:180],file=sys.stderr)
path=Path(__file__).parent/"site"/"data.json"
path.write_text(json.dumps(output,indent=2),encoding="utf-8")
print("Updated dashboard snapshot", {k:len(v) for k,v in output["campaigns"].items()})
