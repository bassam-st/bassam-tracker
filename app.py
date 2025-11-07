from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import sqlite3, json, os
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "events.db")
OWNER_KEY = os.getenv("OWNER_KEY", "CHANGE_ME_OWNER_KEY")
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")]

app = FastAPI(title="Bassam Tracker Lite")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def db():
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts_utc TEXT NOT NULL,
      event TEXT NOT NULL,
      device_id TEXT,
      payload TEXT
    );""")
    return c

@app.post("/track")
async def track(req: Request):
    data = await req.json()
    event = (data or {}).get("event")
    device_id = (data or {}).get("deviceId")
    payload = (data or {}).get("payload", {})
    if event not in ("page_view","search") or not device_id:
        raise HTTPException(400, "bad event or deviceId")
    ts = datetime.now(timezone.utc).isoformat()
    c = db()
    c.execute("INSERT INTO events(ts_utc,event,device_id,payload) VALUES(?,?,?,?)",
              (ts, event, device_id, json.dumps(payload, ensure_ascii=False)))
    c.commit(); c.close()
    return {"ok": True}

def require_owner(auth: str):
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(401, "Auth required")
    if auth.split(" ",1)[1] != OWNER_KEY:
        raise HTTPException(403, "Invalid token")

@app.get("/owner/stats")
def stats(authorization: str = Header(default="")):
    require_owner(authorization)
    c = db()
    total_events   = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    unique_devices = c.execute("SELECT COUNT(DISTINCT device_id) FROM events").fetchone()[0]
    total_searches = c.execute("SELECT COUNT(*) FROM events WHERE event='search'").fetchone()[0]
    daily = c.execute("""
      SELECT substr(ts_utc,1,10) d,
             COUNT(DISTINCT device_id) dau,
             SUM(CASE WHEN event='search' THEN 1 ELSE 0 END) searches
      FROM events GROUP BY d ORDER BY d DESC LIMIT 14
    """).fetchall()
    c.close()
    return {
      "unique_devices": unique_devices,
      "total_searches": total_searches,
      "total_events": total_events,
      "daily": [{"date": d, "unique_devices": dau, "searches": s} for d, dau, s in daily]
    }

@app.get("/owner", response_class=HTMLResponse)
def owner():
    return HTMLResponse("""
<!doctype html><meta charset="utf-8"><title>Bassam — Stats</title>
<style>body{font-family:system-ui,Arial;direction:rtl;margin:20px}</style>
<h2>لوحة المالك</h2>
<input id="k" placeholder="OWNER_KEY"><button onclick="load()">عرض</button>
<pre id="out" style="white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:12px"></pre>
<script>
async function load(){
  const t=document.getElementById('k').value.trim();
  const r=await fetch(''+location.origin+'/owner/stats',{headers:{Authorization:'Bearer '+t}});
  document.getElementById('out').textContent=JSON.stringify(await r.json(),null,2);
}
</script>
""")
