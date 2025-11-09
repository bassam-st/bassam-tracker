from __future__ import annotations
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from collections import Counter, defaultdict
from datetime import datetime, timezone
import base64, json, os, pathlib, requests

app = FastAPI(title="bassam-tracker")

# ========= إعدادات عامة =========
ADMIN_PIN = os.getenv("ADMIN_PIN", "bassam1234")
DATA_FILE = pathlib.Path("events.jsonl")  # تخزين أحداث التتبع
# إعدادات GitHub
GH_TOKEN   = os.getenv("GITHUB_TOKEN")  # ضع التوكن في Render
GH_REPO    = os.getenv("REPO", "bassam-st/bassam-customs-calculator")
GH_PATH    = os.getenv("FILE_PATH", "assets/prices_catalog.json")
GH_USER    = os.getenv("COMMITTER_NAME", "Bassam Tracker")
GH_EMAIL   = os.getenv("COMMITTER_EMAIL", "bot@example.com")

# ========= CORS =========
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

# ========= أدوات التوقيت/التخزين =========
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

# ========= استقبال أحداث التتبع =========
@app.post("/track", response_class=JSONResponse)
async def track(req: Request):
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid json")

    event = {
        "ts": utc_iso(),
        "ip": req.client.host if req.client else None,
        "ua": req.headers.get("user-agent"),
        "event": body.get("event"),
        "deviceId": body.get("deviceId"),
        "payload": body.get("payload") or {},
    }
    if not event["event"] or not event["deviceId"]:
        raise HTTPException(status_code=400, detail="missing event/deviceId")

    append_event(event)
    return {"ok": True}

# ========= تحليل الإحصائيات =========
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

    from collections import Counter
    top = Counter((e.get("payload") or {}).get("q", "").strip() for e in events if e.get("event") == "search")
    top.pop("", None)
    top_searches = [{"q": q, "count": c} for q, c in top.most_common(50)]

    return {
        "unique_devices": len(devices),
        "total_events": total_events,
        "total_searches": total_searches,
        "daily": daily,
        "top_searches": top_searches
    }

# ========= JSON للإحصائيات (محمي) =========
@app.get("/stats", response_class=JSONResponse)
def stats(pin: str = Query(..., min_length=4, max_length=64)):
    if pin != ADMIN_PIN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return compute_stats(load_all_events())

# ========= لوحة المالك =========
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    html = open("dashboard.html", "r", encoding="utf-8").read()
    return HTMLResponse(html)

# ========= مزامنة الأسعار مع GitHub =========
def _gh_headers():
    if not GH_TOKEN:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN not set")
    return {"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"}

def _get_file_sha():
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_PATH}"
    r = requests.get(url, headers=_gh_headers(), timeout=20)
    if r.status_code == 200:
        return r.json().get("sha")
    if r.status_code == 404:
        return None
    raise HTTPException(status_code=502, detail=f"GitHub GET failed: {r.status_code}")

@app.get("/prices", response_class=JSONResponse)
def get_prices():
    """إرجاع آخر نسخة من ملف الأسعار من GitHub."""
    url = f"https://raw.githubusercontent.com/{GH_REPO}/main/{GH_PATH}"
    r = requests.get(url, timeout=20)
    if r.status_code == 200:
        try:
            return r.json()
        except Exception:
            raise HTTPException(status_code=502, detail="bad JSON in repo")
    elif r.status_code == 404:
        return []  # لأول مرة
    else:
        raise HTTPException(status_code=502, detail=f"GitHub raw failed: {r.status_code}")

@app.post("/prices", response_class=JSONResponse)
async def save_prices(req: Request, pin: str = Query(...)):
    """حفظ المصفوفة القادمة من التطبيق إلى GitHub (محمي بالـ PIN)."""
    if pin != ADMIN_PIN:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    if not isinstance(body, list):
        raise HTTPException(status_code=400, detail="expected list")

    payload_str = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    content_b64 = base64.b64encode(payload_str.encode("utf-8")).decode("ascii")
    sha = _get_file_sha()

    url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_PATH}"
    data = {
        "message": f"Update prices_catalog.json ({utc_iso()})",
        "content": content_b64,
        "branch": "main",
        "committer": {"name": GH_USER, "email": GH_EMAIL}
    }
    if sha:
        data["sha"] = sha

    r = requests.put(url, headers=_gh_headers(), json=data, timeout=30)
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"GitHub PUT failed: {r.status_code} {r.text[:200]}")

    return {"ok": True, "committed": True}

@app.get("/", response_class=PlainTextResponse)
def root():
    return "bassam-tracker OK"
