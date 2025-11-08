# app.py
from __future__ import annotations
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json, os, pathlib

app = FastAPI(title="bassam-tracker")

# ===== إعدادات عامة =====
ADMIN_PIN = os.getenv("ADMIN_PIN", "bassam1234")

# مسار التخزين: يُفضَّل قرص دائم على Render (انظر الخطوة 4)
DATA_FILE = pathlib.Path(os.getenv("DATA_FILE", "/var/data/events.jsonl"))

# أصول مسموحة CORS — عدّلها إلى نطاقات تطبيقك
ALLOW_ORIGINS = os.getenv("ALLOW_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== تخزين سطر-بسطر =====
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

# ===== استقبال أحداث التتبّع =====
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

# ===== حساب الإحصائيات =====
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

    top = Counter((e.get("payload") or {}).get("q", "").strip() for e in events if e.get("event") == "search")
    if "" in top:
        del top[""]
    top_searches = [{"q": q, "count": c} for q, c in top.most_common(50)]

    return {
        "unique_devices": len(devices),
        "total_events": total_events,
        "total_searches": total_searches,
        "daily": daily,
        "top_searches": top_searches,
    }

# ===== JSON محمي =====
@app.get("/stats", response_class=JSONResponse)
def stats(pin: str = Query(..., min_length=4, max_length=64)):
    if pin != ADMIN_PIN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return compute_stats(load_all_events())

# ===== لوحة التحكم (صفحة واحدة) =====
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>لوحة تحكم المالك</title>
<style>
:root{--green:#16a34a;--ink:#0f172a;--muted:#64748b;--bg:#f1f5f9;--card:#fff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:'Noto Kufi Arabic',system-ui,sans-serif;color:var(--ink)}
.wrap{max-width:980px;margin:18px auto;padding:0 12px}
.top{background:var(--green);color:#fff;padding:14px 16px;border-radius:12px;font-weight:900;font-size:20px}
.row{display:flex;gap:12px;flex-wrap:wrap;margin-top:12px}
.card{flex:1 1 220px;background:var(--card);border:1px solid #e5e7eb;border-radius:12px;padding:14px;box-shadow:0 4px 16px rgba(0,0,0,.05)}
.kpi{font-size:36px;font-weight:900;margin-top:6px}
.muted{color:var(--muted);font-size:12px}
.controls{display:flex;gap:8px;align-items:center;margin-top:12px}
input{padding:10px 12px;border:1px solid #cbd5e1;border-radius:10px}
button{padding:10px 12px;border:none;border-radius:10px;background:#0ea5e9;color:#fff;font-weight:800;cursor:pointer}
table{width:100%;border-collapse:collapse}
th,td{padding:8px;border-bottom:1px dashed #e5e7eb;text-align:start}
canvas{width:100%;height:220px;display:block}
</style></head>
<body><div class="wrap">
  <div class="top">📊 لوحة تحكم المالك</div>
  <div class="controls">
    <input id="pin" placeholder="PIN" value="bassam1234">
    <button id="load">عرض</button>
    <span class="muted" id="msg"></span>
  </div>
  <div class="row">
    <div class="card"><div class="muted">أجهزة فريدة</div><div class="kpi" id="kpi_devices">–</div></div>
    <div class="card"><div class="muted">إجمالي الأحداث</div><div class="kpi" id="kpi_events">–</div></div>
    <div class="card"><div class="muted">إجمالي عمليات البحث</div><div class="kpi" id="kpi_searches">–</div></div>
  </div>
  <div class="row">
    <div class="card" style="flex:2 1 420px"><div class="muted">المستخدمون والبحث حسب اليوم</div><canvas id="chart"></canvas></div>
    <div class="card" style="flex:1 1 260px"><div class="muted">أعلى كلمات البحث</div><table id="top"></table></div>
  </div>
</div>
<script>
const $=id=>document.getElementById(id);
const pin=$('pin'), btn=$('load'), msg=$('msg');
const kpi_devices=$('kpi_devices'), kpi_events=$('kpi_events'), kpi_searches=$('kpi_searches');
const topTbl=$('top'); const chartEl=$('chart');
async function loadStats(){
  msg.textContent='جاري التحميل…';
  try{
    const r = await fetch(`/stats?pin=${encodeURIComponent(pin.value)}`);
    if(!r.ok) throw new Error('HTTP '+r.status);
    const data = await r.json();
    kpi_devices.textContent = data.unique_devices ?? 0;
    kpi_events.textContent  = data.total_events ?? 0;
    kpi_searches.textContent= data.total_searches ?? 0;
    const rows = (data.top_searches||[]).map(x=>`<tr><td>${escapeHtml(x.q)}</td><td>${x.count}</td></tr>`);
    topTbl.innerHTML = `<tr><th>الكلمة</th><th>العدد</th></tr>` + (rows.join('')||'<tr><td colspan="2">لا يوجد بيانات</td></tr>');
    drawBars(chartEl, data.daily||[], {a:'unique_devices', b:'searches'});
    msg.textContent='تم.';
  }catch(e){ msg.textContent='فشل: '+e.message; }
}
btn.addEventListener('click', loadStats);
function escapeHtml(s){return String(s||'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));}
function drawBars(canvas, daily, keys){
  const d = daily.slice(-14), labels=d.map(x=>x.date), A=d.map(x=>+x[keys.a]||0), B=d.map(x=>+x[keys.b]||0);
  const W=canvas.clientWidth,H=canvas.clientHeight; canvas.width=W*devicePixelRatio; canvas.height=H*devicePixelRatio;
  const ctx=canvas.getContext('2d'); ctx.scale(devicePixelRatio,devicePixelRatio); ctx.clearRect(0,0,W,H);
  const max=Math.max(1,...A,...B), pad=28, innerW=W-pad*2, innerH=H-pad*2, n=labels.length||1, groupW=innerW/n;
  ctx.strokeStyle='#e5e7eb'; ctx.beginPath(); ctx.moveTo(pad,H-pad); ctx.lineTo(W-pad,H-pad); ctx.stroke();
  for(let i=0;i<n;i++){
    const x0=pad+i*groupW, w=Math.max(6,groupW*0.36), gap=groupW*0.08;
    const hA=innerH*(A[i]/max), hB=innerH*(B[i]/max);
    ctx.fillStyle='#86efac'; ctx.fillRect(x0+gap, H-pad-hA, w, hA);
    ctx.fillStyle='#93c5fd'; ctx.fillRect(x0+gap+w+gap, H-pad-hB, w, hB);
    ctx.fillStyle='#64748b'; ctx.font='10px system-ui'; ctx.fillText(String(labels[i]||'').slice(5), x0+gap, H-pad+12);
  }
}
loadStats();
</script>
</body></html>
"""
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(DASHBOARD_HTML)

# فحص سريع
@app.get("/", response_class=PlainTextResponse)
def root():
    return "bassam-tracker OK"
