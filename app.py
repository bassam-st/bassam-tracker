# app.py — Bassam Tracker (FINAL)
from __future__ import annotations
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json, pathlib, io

app = FastAPI(title="bassam-tracker")

# ===== إعدادات عامة =====
ADMIN_PIN  = "bassam1234"
DATA_FILE  = pathlib.Path("events.jsonl")  # تخزين سطر-بسطر

# ===== CORS =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

# ===== أدوات تخزين =====
def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def append_event(event: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

def load_all_events() -> list[dict]:
    if not DATA_FILE.exists(): return []
    out = []
    with DATA_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try: out.append(json.loads(line))
            except: pass
    return out

# ===== استقبال الأحداث من التطبيق الأم =====
@app.post("/track", response_class=JSONResponse)
async def track(req: Request):
    """
    يَستقبل JSON: {event, deviceId, payload?}
    """
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

# ===== تحليل الإحصائيات =====
def compute_stats(events: list[dict]) -> dict:
    devices = {e.get("deviceId") for e in events if e.get("deviceId")}
    total_events   = len(events)
    total_searches = sum(1 for e in events if e.get("event") == "search")

    # تجميع يومي
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

    # أعلى كلمات البحث
    top = Counter((e.get("payload") or {}).get("q", "").strip()
                  for e in events if e.get("event") == "search")
    top.pop("", None)
    top_searches = [{"q": q, "count": c} for q, c in top.most_common(50)]

    # آخر 20 حدثًا
    latest = events[-20:]

    return {
        "unique_devices": len(devices),
        "total_events": total_events,
        "total_searches": total_searches,
        "daily": daily,
        "top_searches": top_searches,
        "latest": latest,
    }

# ===== JSON محمي =====
@app.get("/stats", response_class=JSONResponse)
def stats(pin: str = Query(..., min_length=4, max_length=64)):
    if pin != ADMIN_PIN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return compute_stats(load_all_events())

# ===== تصدير/تفريغ (للمالك) =====
@app.get("/export")
def export(pin: str = Query(...)):
    if pin != ADMIN_PIN: raise HTTPException(status_code=403, detail="Forbidden")
    data = DATA_FILE.read_bytes() if DATA_FILE.exists() else b""
    return FileResponse(path=DATA_FILE, filename="events.jsonl",
                        media_type="text/plain") if DATA_FILE.exists() \
           else PlainTextResponse("", media_type="text/plain")

@app.post("/clear")
def clear(pin: str = Query(...)):
    if pin != ADMIN_PIN: raise HTTPException(status_code=403, detail="Forbidden")
    if DATA_FILE.exists(): DATA_FILE.unlink()
    return {"ok": True}

# ===== تقديم tracker.js مباشرة (اختياري) =====
@app.get("/tracker.js")
def tracker_js():
    return FileResponse("tracker.js", media_type="application/javascript")

# ===== لوحة المالك =====
DASHBOARD_FALLBACK = """<!DOCTYPE html><meta charset="utf-8"><meta name=viewport content="width=device-width,initial-scale=1">
<title>لوحة تحكم المالك</title>
<style>body{font-family:'Noto Kufi Arabic',system-ui;background:#f1f5f9;margin:0}
.wrap{max-width:1080px;margin:18px auto;padding:0 12px} .top{background:#16a34a;color:#fff;padding:14px 16px;border-radius:12px;font-weight:900;font-size:20px}
.controls{display:flex;gap:8px;align-items:center;margin:12px 0} input{padding:10px;border:1px solid #cbd5e1;border-radius:10px}
button{padding:10px 12px;border:none;border-radius:10px;background:#0ea5e9;color:#fff;font-weight:800;cursor:pointer}
.row{display:flex;gap:12px;flex-wrap:wrap} .card{flex:1 1 260px;background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px;box-shadow:0 4px 16px rgba(0,0,0,.05)}
.kpi{font-size:36px;font-weight:900;margin-top:6px} .muted{color:#64748b;font-size:12px}
table{width:100%;border-collapse:collapse} th,td{padding:8px;border-bottom:1px dashed #e5e7eb;text-align:start;font-size:13px}
th{background:#f8fafc} .mono{font-family:ui-monospace,Menlo,Consolas,monospace} canvas{width:100%;height:240px;display:block}</style>
<div class=wrap>
<div class=top>📊 لوحة تحكم المالك</div>
<div class=controls>
  <input id=pin placeholder=PIN value=bassam1234>
  <button id=load>عرض</button>
  <button id=export>تصدير</button>
  <button id=clear>تفريغ</button>
  <span id=msg class=muted></span>
</div>
<div class=row>
  <div class=card><div class=muted>أجهزة فريدة</div><div id=kpi_devices class=kpi>–</div></div>
  <div class=card><div class=muted>إجمالي الأحداث</div><div id=kpi_events class=kpi>–</div></div>
  <div class=card><div class=muted>إجمالي عمليات البحث</div><div id=kpi_searches class=kpi>–</div></div>
</div>
<div class=row>
  <div class=card style="flex:2 1 520px"><div class=muted>المستخدمون والبحث حسب اليوم (آخر 14 يوم)</div><canvas id=chart></canvas></div>
  <div class=card style="flex:1 1 280px"><div class=muted>أعلى كلمات البحث</div><table id=top><tr><th>الكلمة</th><th>العدد</th></tr></table></div>
</div>
<div class=card style="margin-top:12px">
  <div class=muted style="margin-bottom:6px">آخر 20 حدثًا</div>
  <table id=latest><tr><th>الوقت (UTC)</th><th>IP</th><th>الحدث</th><th>الكلمة/المسار</th><th>المتصفح</th></tr></table>
</div></div>
<script>
const $=id=>document.getElementById(id);const pin=$('pin'),btn=$('load'),msg=$('msg');
const kpiD=$('kpi_devices'),kpiE=$('kpi_events'),kpiS=$('kpi_searches'),topTbl=$('top'),chartEl=$('chart'),latestTbl=$('latest');
$('export').onclick=()=>open('/export?pin='+encodeURIComponent(pin.value),'_blank');
$('clear').onclick=async()=>{if(!confirm('تفريغ جميع السجلات؟'))return;const r=await fetch('/clear?pin='+encodeURIComponent(pin.value),{method:'POST'});msg.textContent=r.ok?'تم':'فشل';load();};
btn.onclick=load;function esc(s){return String(s||'').replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));}
async function load(){msg.textContent='...';try{const r=await fetch('/stats?pin='+encodeURIComponent(pin.value));if(!r.ok)throw new Error('PIN خطأ');const d=await r.json();
kpiD.textContent=d.unique_devices??0;kpiE.textContent=d.total_events??0;kpiS.textContent=d.total_searches??0;
topTbl.innerHTML='<tr><th>الكلمة</th><th>العدد</th></tr>'+((d.top_searches||[]).map(x=>`<tr><td>${esc(x.q)}</td><td>${x.count}</td></tr>`).join('')||'<tr><td colspan=2>لا بيانات</td></tr>');
latestTbl.innerHTML=`<tr><th>الوقت (UTC)</th><th>IP</th><th>الحدث</th><th>الكلمة/المسار</th><th>المتصفح</th></tr>`+(d.latest||[]).map(e=>{
const p=e.payload||{};const qp=p.q?`🔎 ${esc(p.q)}`:(p.path?`📄 ${esc(p.path)}`:'');return `<tr>
<td class=mono>${esc(e.ts||'')}</td><td class=mono>${esc(e.ip||'-')}</td><td>${esc(e.event||'-')}</td><td>${qp}</td>
<td title="${esc(e.ua||'')}">${esc(String(e.ua||'').slice(0,38))}…</td></tr>`;}).join('');
draw(chartEl,d.daily||[],{a:'unique_devices',b:'searches'});msg.textContent='تم.';}catch(e){msg.textContent='فشل: '+e.message;}}
function draw(c,d,k){d=d.slice(-14);const L=d.map(x=>x.date),A=d.map(x=>+x[k.a]||0),B=d.map(x=>+x[k.b]||0);const W=c.clientWidth,H=c.clientHeight;c.width=W*devicePixelRatio;c.height=H*devicePixelRatio;
const x=c.getContext('2d');x.scale(devicePixelRatio,devicePixelRatio);x.clearRect(0,0,W,H);const M=Math.max(1,...A,...B),P=28,iw=W-P*2,ih=H-P*2,n=L.length||1,g=iw/n;
x.strokeStyle='#e5e7eb';x.beginPath();x.moveTo(P,H-P);x.lineTo(W-P,H-P);x.stroke();for(let i=0;i<n;i++){const x0=P+i*g,w=Math.max(6,g*.36),gap=g*.08,hA=ih*(A[i]/M),hB=ih*(B[i]/M);
x.fillStyle='#86efac';x.fillRect(x0+gap,H-P-hA,w,hA);x.fillStyle='#93c5fd';x.fillRect(x0+gap+w+gap,H-P-hB,w,hB);x.fillStyle='#64748b';x.font='10px system-ui';x.fillText(String(L[i]||'').slice(5),x0+gap,H-P+12);}}
load();
</script>"""
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    # إن وُجد dashboard.html في نفس المجلد سيتم تقديمه، وإلا نستخدم النسخة المدمجة
    p = pathlib.Path("dashboard.html")
    if p.exists(): return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse(DASHBOARD_FALLBACK)

# ===== صحّة السيرفر =====
@app.get("/", response_class=PlainTextResponse)
def root():
    return "bassam-tracker OK"
