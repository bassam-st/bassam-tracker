# app.py — Bassam Tracker (FINAL)
from __future__ import annotations
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json, os, pathlib

app = FastAPI(title="bassam-tracker")

# ========= الإعدادات =========
ADMIN_PIN = os.getenv("ADMIN_PIN", "bassam1234")

# تخزين دائم: استخدم /data إن كان موجودًا (Render Disk) وإلا خزّن محليًا
DATA_DIR = pathlib.Path(os.getenv("DATA_DIR", "/data"))
if not DATA_DIR.exists():
    DATA_DIR = pathlib.Path(".")
DATA_FILE = DATA_DIR / "events.jsonl"

# CORS + ضغط GZip
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=512)

# ========= أدوات التخزين =========
def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def append_event(event: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

def load_all_events() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    out = []
    with DATA_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out

# ========= استقبال الأحداث من التطبيق الأم =========
@app.post("/track", response_class=JSONResponse)
async def track(req: Request):
    """
    body = { "event": "page_view" | "search" | ...,
             "deviceId": "uuid",
             "payload": {...} }
    """
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid json")

    if not body.get("event") or not body.get("deviceId"):
        raise HTTPException(status_code=400, detail="missing event/deviceId")

    event = {
        "ts": utc_iso(),
        "ip": req.client.host if req.client else None,
        "ua": req.headers.get("user-agent"),
        "event": body.get("event"),
        "deviceId": body.get("deviceId"),
        "payload": body.get("payload") or {},
    }
    append_event(event)
    return {"ok": True}

# ========= حساب الإحصاءات =========
def compute_stats(events: list[dict]) -> dict:
    devices = {e.get("deviceId") for e in events if e.get("deviceId")}
    total_events = len(events)
    total_searches = sum(1 for e in events if e.get("event") == "search")

    daily_raw = defaultdict(lambda: {"date": None, "unique_devices": 0, "searches": 0})
    devices_per_day = defaultdict(set)
    for e in events:
        ts = e.get("ts")
        try:
            d = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc).date().isoformat()
        except Exception:
            d = datetime.utcnow().date().isoformat()
        devices_per_day[d].add(e.get("deviceId"))
        if e.get("event") == "search":
            daily_raw[d]["searches"] += 1
        daily_raw[d]["date"] = d

    for d in list(daily_raw.keys()):
        daily_raw[d]["unique_devices"] = len({x for x in devices_per_day[d] if x})

    daily = sorted(daily_raw.values(), key=lambda x: x["date"])

    top = Counter((e.get("payload") or {}).get("q", "").strip()
                  for e in events if e.get("event") == "search")
    top.pop("", None)
    top_searches = [{"q": q, "count": c} for q, c in top.most_common(50)]

    latest = sorted(events, key=lambda x: x.get("ts", ""), reverse=True)[:20]

    return {
        "unique_devices": len(devices),
        "total_events": total_events,
        "total_searches": total_searches,
        "daily": daily,
        "top_searches": top_searches,
        "latest": latest
    }

# ========= واجهات الإدارة (محمي PIN) =========
@app.get("/stats", response_class=JSONResponse)
def stats(pin: str = Query(..., min_length=4, max_length=64)):
    if pin != ADMIN_PIN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return compute_stats(load_all_events())

@app.get("/export", response_class=FileResponse)
def export(pin: str = Query(...)):
    if pin != ADMIN_PIN:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not DATA_FILE.exists():
        raise HTTPException(status_code=404, detail="no data")
    return FileResponse(DATA_FILE, media_type="text/plain", filename="events.jsonl")

@app.post("/clear", response_class=JSONResponse)
def clear(pin: str = Query(...)):
    if pin != ADMIN_PIN:
        raise HTTPException(status_code=403, detail="Forbidden")
    if DATA_FILE.exists():
        DATA_FILE.unlink()
    return {"ok": True}

# ========= صفحات جاهزة =========
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    with open("dashboard.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"

@app.get("/", response_class=PlainTextResponse)
def root():
    return "bassam-tracker OK"
