// assets/tracker.js — يتتبع الزوار وعمليات البحث
(function(){
  const TRACK_URL = "https://bassam-tracker.onrender.com/track";

  // إنشاء رقم مميز لكل جهاز (مجهول)
  function uuid(){return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{
    const r = crypto.getRandomValues(new Uint8Array(1))[0] & 15;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });}
  const LS = localStorage;
  let deviceId = LS.getItem("deviceId");
  if(!deviceId){ deviceId = uuid(); LS.setItem("deviceId", deviceId); }

  // إرسال البيانات
  async function send(event, payload){
    const body = JSON.stringify({ event, deviceId, payload: payload||{} });
    try{
      if (navigator.sendBeacon) {
        const blob = new Blob([body], {type:"application/json"});
        navigator.sendBeacon(TRACK_URL, blob);
      } else {
        await fetch(TRACK_URL, {method:"POST", headers:{ "Content-Type":"application/json" }, body});
      }
    }catch(_){}
  }

  // عند فتح الصفحة
  document.addEventListener("DOMContentLoaded", ()=>{
    send("page_view", { path: location.pathname, title: document.title });
  });

  // عند تنفيذ أي عملية بحث (input type="search")
  document.addEventListener("submit", (e)=>{
    try{
      const f = e.target;
      const q = f.querySelector('input[type="search"], input[name*="search"], input[id*="search"], input[name*="query"], input[id*="query"]');
      const val = q ? String(q.value||"").trim() : "";
      if (val) send("search", { q: val, page: location.pathname });
    }catch(_){}
  }, true);

  // يمكن استدعاؤها يدويًا من أي مكان
  window.trackSearch = (q)=> send("search", { q: String(q||"").trim(), page: location.pathname });
})();
