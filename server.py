"""
Skyler BI — FastAPI Backend
Serves the SPA and provides JSON APIs for all data.
"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import json, uuid, os, sys

sys.path.insert(0, os.path.dirname(__file__))

app = FastAPI(title="Skyler BI API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Simple in-process cache ───────────────────────────────────────────────────
_cache = {}

def get_deals():
    if "deals" not in _cache:
        from monday_client import _fetch_all_deals
        _cache["deals"] = _fetch_all_deals()
    return _cache["deals"]

def get_work_orders():
    if "wo" not in _cache:
        from monday_client import _fetch_all_work_orders
        _cache["wo"] = _fetch_all_work_orders()
    return _cache["wo"]

def safe_num(v):
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None

def fmt_inr(val):
    if val is None: return "N/A"
    try: val = float(val)
    except: return "N/A"
    if val >= 1e7:   return f"₹{val/1e7:.2f} Cr"
    elif val >= 1e5: return f"₹{val/1e5:.1f} L"
    else:            return f"₹{val:,.0f}"

# ── Chat session store ────────────────────────────────────────────────────────
_sessions = {}

def get_or_create_session(session_id: str):
    if session_id not in _sessions:
        from agent import create_chat
        _sessions[session_id] = create_chat()
    return _sessions[session_id]

# ── Deals API ─────────────────────────────────────────────────────────────────
@app.get("/api/deals")
def api_deals(sector: str = "", stage: str = "", status: str = ""):
    raw = get_deals()
    df = pd.DataFrame(raw)
    if df.empty:
        return {"total": 0, "summary": {}, "records": [], "filters": {}}

    # Parse numeric before any fillna
    if "Masked Deal value" in df.columns:
        df["_val"] = pd.to_numeric(df["Masked Deal value"], errors="coerce")
    else:
        df["_val"] = float("nan")

    # Compute summary on full dataset
    total_val  = df["_val"].sum()
    null_vals  = int(df["_val"].isna().sum())
    open_c     = int((df.get("Deal Status","") == "Open").sum())
    won_c      = int((df.get("Deal Status","") == "Won").sum())
    dead_c     = int((df.get("Deal Status","") == "Dead").sum())
    hold_c     = int((df.get("Deal Status","") == "On Hold").sum())

    # Filter options
    sectors  = sorted([s for s in df.get("Sector","").unique()     if s and not pd.isna(s)])
    stages   = sorted([s for s in df.get("Deal Stage","").unique() if s and not pd.isna(s)])
    statuses = sorted([s for s in df.get("Deal Status","").unique()if s and not pd.isna(s)])

    # Apply filters
    if sector: df = df[df.get("Sector","") == sector]
    if stage:  df = df[df.get("Deal Stage","") == stage]
    if status: df = df[df.get("Deal Status","") == status]

    # Build records
    cols = ["Deal Name","Client Code","Sector","Deal Stage","Deal Status",
            "Closure Probability","Masked Deal value","Tentative Close Date","Owner code","Product deal"]
    existing = [c for c in cols if c in df.columns]
    rows = []
    for _, r in df[existing].iterrows():
        row = {c: (r[c] if r[c] and not (isinstance(r[c], float) and pd.isna(r[c])) else "") for c in existing}
        row["_val_num"] = safe_num(r.get("Masked Deal value"))
        rows.append(row)

    return {
        "total": len(df),
        "board_total": len(pd.DataFrame(raw)),
        "summary": {
            "total_value": float(total_val) if not pd.isna(total_val) else 0,
            "total_value_fmt": fmt_inr(total_val),
            "null_values": null_vals,
            "open": open_c, "won": won_c, "dead": dead_c, "on_hold": hold_c,
        },
        "filters": {"sectors": sectors, "stages": stages, "statuses": statuses},
        "records": rows,
    }

# ── Work Orders API ───────────────────────────────────────────────────────────
@app.get("/api/work_orders")
def api_work_orders(sector: str = "", exec_status: str = "", nature: str = ""):
    raw = get_work_orders()
    df = pd.DataFrame(raw)
    if df.empty:
        return {"total": 0, "summary": {}, "records": [], "filters": {}}

    AMT  = "Amount in Rupees (Excl of GST) (Masked)"
    RECV = "Amount Receivable (Masked)"
    TBIL = "Amount to be billed in Rs. (Exl. of GST) (Masked)"
    COLL = "Collected Amount in Rupees (Incl of GST.) (Masked)"

    for col in [AMT, RECV, TBIL, COLL]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["Probable Start Date", "Probable End Date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    if "Probable Start Date" in df.columns and "Probable End Date" in df.columns:
        df["_exec_days"] = (df["Probable End Date"] - df["Probable Start Date"]).dt.days.clip(lower=0)

    # Summary on full dataset
    total_rev   = float(df[AMT].sum())  if AMT  in df.columns else 0
    total_recv  = float(df[RECV].sum()) if RECV in df.columns else 0
    total_tbill = float(df[TBIL].sum()) if TBIL in df.columns else 0
    total_coll  = float(df[COLL].sum()) if COLL in df.columns else 0
    ongoing_c   = int((df.get("Execution Status","") == "Ongoing").sum())
    completed_c = int((df.get("Execution Status","") == "Completed").sum())
    avg_days    = int(df["_exec_days"].median()) if "_exec_days" in df.columns and df["_exec_days"].notna().any() else 0

    # Filter options
    sectors  = sorted([s for s in df.get("Sector","").unique()           if s and not (isinstance(s,float) and pd.isna(s))])
    e_stats  = sorted([s for s in df.get("Execution Status","").unique() if s and not (isinstance(s,float) and pd.isna(s))])
    natures  = sorted([s for s in df.get("Nature of Work","").unique()   if s and not (isinstance(s,float) and pd.isna(s))])

    # Apply filters
    if sector:      df = df[df.get("Sector","") == sector]
    if exec_status: df = df[df.get("Execution Status","") == exec_status]
    if nature:      df = df[df.get("Nature of Work","") == nature]

    # Format dates back to string
    for col in ["Probable Start Date", "Probable End Date"]:
        if col in df.columns:
            df[col] = df[col].dt.strftime("%d %b %Y").fillna("")

    cols = ["Deal name masked","Serial #","Customer Name Code","Sector",
            "Nature of Work","Execution Status","Invoice Status","Billing Status",
            AMT, RECV, TBIL, "Probable Start Date","Probable End Date"]
    existing = [c for c in cols if c in df.columns]

    rows = []
    for _, r in df[existing].iterrows():
        row = {}
        for c in existing:
            v = r[c]
            if isinstance(v, float) and pd.isna(v):
                row[c] = None
            else:
                row[c] = v
        rows.append(row)

    return {
        "total": len(df),
        "board_total": len(pd.DataFrame(raw)),
        "summary": {
            "total_revenue": total_rev, "total_revenue_fmt": fmt_inr(total_rev),
            "total_recv": total_recv,   "total_recv_fmt": fmt_inr(total_recv),
            "total_tbill": total_tbill, "total_tbill_fmt": fmt_inr(total_tbill),
            "total_coll": total_coll,   "total_coll_fmt": fmt_inr(total_coll),
            "ongoing": ongoing_c, "completed": completed_c, "avg_days": avg_days,
        },
        "filters": {"sectors": sectors, "exec_statuses": e_stats, "natures": natures},
        "records": rows,
    }

# ── Chat API ──────────────────────────────────────────────────────────────────
class ChatReq(BaseModel):
    message: str
    session_id: str = ""

@app.post("/api/chat")
def api_chat(body: ChatReq):
    sid = body.session_id or str(uuid.uuid4())
    session = get_or_create_session(sid)
    from agent import ask
    result = ask(session, body.message)
    if isinstance(result, dict):
        return {"session_id": sid, **result}
    return {"session_id": sid, "answer": str(result), "chart": None}

# ── Leadership API ─────────────────────────────────────────────────────────────
@app.get("/api/leadership")
def api_leadership():
    deals_raw = get_deals()
    wo_raw    = get_work_orders()
    ddf = pd.DataFrame(deals_raw)
    wdf = pd.DataFrame(wo_raw)

    AMT  = "Amount in Rupees (Excl of GST) (Masked)"
    RECV = "Amount Receivable (Masked)"
    TBIL = "Amount to be billed in Rs. (Exl. of GST) (Masked)"

    if "Masked Deal value" in ddf.columns:
        ddf["_val"] = pd.to_numeric(ddf["Masked Deal value"], errors="coerce")
    for col in [AMT, RECV, TBIL]:
        if col in wdf.columns:
            wdf[col] = pd.to_numeric(wdf[col], errors="coerce")

    total_pipeline = float(ddf["_val"].sum()) if "_val" in ddf.columns else 0
    total_revenue  = float(wdf[AMT].sum())    if AMT   in wdf.columns else 0
    exec_gap       = float(wdf[TBIL].sum())   if TBIL  in wdf.columns else 0
    receivables    = float(wdf[RECV].sum())   if RECV  in wdf.columns else 0
    open_deals     = int((ddf.get("Deal Status","") == "Open").sum())
    won_deals      = int((ddf.get("Deal Status","") == "Won").sum())

    # Cross-board chart data
    ds = ddf[ddf.get("Sector","") != ""].groupby("Sector").size().reset_index(name="deals") if "Sector" in ddf.columns else pd.DataFrame()
    ws = wdf[wdf.get("Sector","") != ""].groupby("Sector").size().reset_index(name="wo")    if "Sector" in wdf.columns else pd.DataFrame()

    if not ds.empty and not ws.empty:
        cross = pd.merge(ds, ws, on="Sector", how="outer").fillna(0).sort_values("deals", ascending=False)
        chart_sectors = cross["Sector"].tolist()
        chart_deals   = cross["deals"].astype(int).tolist()
        chart_wo      = cross["wo"].astype(int).tolist()
    else:
        chart_sectors, chart_deals, chart_wo = [], [], []

    # Top sectors by revenue
    if "Sector" in wdf.columns and AMT in wdf.columns:
        top_sec = (wdf[wdf["Sector"].astype(str) != ""].groupby("Sector")[AMT]
                   .sum().sort_values(ascending=False).head(5))
        top_sectors = [{"sector": s, "value": float(v), "value_fmt": fmt_inr(v)} for s, v in top_sec.items()]
    else:
        top_sectors = []

    return {
        "kpis": {
            "total_pipeline": total_pipeline, "total_pipeline_fmt": fmt_inr(total_pipeline),
            "total_revenue": total_revenue,   "total_revenue_fmt": fmt_inr(total_revenue),
            "exec_gap": exec_gap,             "exec_gap_fmt": fmt_inr(exec_gap),
            "receivables": receivables,       "receivables_fmt": fmt_inr(receivables),
            "open_deals": open_deals, "won_deals": won_deals,
        },
        "cross_chart": {"sectors": chart_sectors, "deals": chart_deals, "wo": chart_wo},
        "top_sectors": top_sectors,
    }

class BriefingReq(BaseModel):
    session_id: str = ""

@app.post("/api/leadership/briefing")
def api_briefing(body: BriefingReq):
    sid = body.session_id or "leadership_" + str(uuid.uuid4())
    session = get_or_create_session(sid)
    from agent import ask
    result = ask(session,
        "Prepare a concise executive leadership briefing: "
        "1) Overall business health across all sectors, "
        "2) Top performing sectors by deals and revenue, "
        "3) Key risks — sectors with large receivables or billing gaps, "
        "4) Pipeline outlook — open deals and closure probability. "
        "Be specific with numbers. Flag data quality issues.")
    if isinstance(result, dict):
        return {"session_id": sid, **result}
    return {"session_id": sid, "answer": str(result), "chart": None}

class SimReq(BaseModel):
    win_rate_delta: float = 0.0
    billing_efficiency: float = 50.0
    focus_sector: str = "All"
    sector_growth: float = 0.0
    projected_revenue_cr: float = 0.0
    projected_cashflow_cr: float = 0.0
    session_id: str = ""

@app.post("/api/simulator/strategy")
def api_simulator_strategy(body: SimReq):
    sid = body.session_id or "sim_" + str(uuid.uuid4())
    session = get_or_create_session(sid)
    from agent import ask
    prompt = (
        f"You are the strategic advisor for Skylark Drones leadership. "
        f"The executive is running a What-If Scenario with these parameters:\n"
        f"- Pipeline Win Rate Change: {body.win_rate_delta:+.0f}%\n"
        f"- Unbilled & Receivables Resolution Rate: {body.billing_efficiency:.0f}%\n"
        f"- Focus Sector: {body.focus_sector} (Target Growth: {body.sector_growth:+.0f}%)\n"
        f"- Projected Realized Revenue: ₹{body.projected_revenue_cr:.2f} Cr\n"
        f"- Projected Cash Flow Inflow: ₹{body.projected_cashflow_cr:.2f} Cr\n\n"
        f"Provide a concise, 3-point tactical executive action plan: "
        f"1) Specific deal stages and accounts to mobilize, "
        f"2) Operational bottlenecks (drone pilot reallocation, billing milestones), "
        f"3) Immediate quarterly decision recommendation. Ground it in Skylark's real data."
    )
    result = ask(session, prompt)
    if isinstance(result, dict):
        return {"session_id": sid, **result}
    return {"session_id": sid, "answer": str(result), "chart": None}

# ── Static files ──────────────────────────────────────────────────────────────
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

from fastapi.responses import HTMLResponse

@app.get("/")
def root():
    paths_to_check = [
        os.path.join(static_dir, "index.html"),
        os.path.join(os.path.dirname(__file__), "static", "index.html"),
        os.path.join(os.path.dirname(__file__), "index.html"),
        "static/index.html",
        "index.html",
    ]
    for p in paths_to_check:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h2>Skyler BI Server Running</h2><p>Please ensure static/index.html is uploaded.</p>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8080, reload=False)
