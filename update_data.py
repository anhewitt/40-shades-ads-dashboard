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
P="sponsored_products_campaign__"
T="sponsored_products_search_term__"
CAMPAIGNS={"Teaching Hell - UK - Auto Test":"Teaching Hell","Corporate Misery - UK - Auto Test":"Corporate Misery"}

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
        "campaigns":{x:[] for x in CAMPAIGNS.values()},"search_terms":{},"partial":False}
fields=["date",P+"campaign",P+"impressions",P+"clicks",P+"cost",P+"attributedsales14d",P+"attributedconversions14d"]
rows=pull(fields)
for r in rows:
    name=CAMPAIGNS.get(r.get(P+"campaign",r.get("campaign")))
    if not name:continue
    date=str(r.get("date",""))[:10]
    if not date:continue
    output["campaigns"][name].append({"date":date,"impressions":num(r.get(P+"impressions")),
        "clicks":num(r.get(P+"clicks")),"spend":num(r.get(P+"cost")),
        "sales":num(r.get(P+"attributedsales14d")),"orders":num(r.get(P+"attributedconversions14d"))})
for days in output["campaigns"].values(): days.sort(key=lambda r:r["date"])
try:
    search=pull([T+"campaign_name",T+"search_term",T+"clicks",T+"cost",T+"sales_14d"])
    for campaign,short in CAMPAIGNS.items():
        output["search_terms"][short]=sorted(
            [{"term":str(r.get(T+"search_term") or ""),"clicks":num(r.get(T+"clicks")),
              "spend":num(r.get(T+"cost")),"sales":num(r.get(T+"sales_14d"))}
             for r in search if r.get(T+"campaign_name")==campaign and r.get(T+"search_term")],
            key=lambda x:x["spend"] or 0,reverse=True)[:15]
except Exception as exc:
    output["partial"]=True
    print("Search-term query unavailable:",str(exc)[:180],file=sys.stderr)
path=Path(__file__).parent/"site"/"data.json"
path.write_text(json.dumps(output,indent=2),encoding="utf-8")
print("Updated dashboard snapshot", {k:len(v) for k,v in output["campaigns"].items()})
