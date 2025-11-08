// assets/tracker.js
(function(){
  const TRACK_URL = "https://bassam-tracker.onrender.com/track";

  function uuid(){return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{
    const r = crypto.getRandomValues(new Uint8Array(1))[0] & 15;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });}

  const LS = localStorage;
  let deviceId = LS.getItem("deviceId");
  if(!deviceId){ deviceId = uuid(); LS.setItem("deviceId", deviceId); }

  async function send(event, payload){
    const body = JSON.stringify({ event, deviceId, payload: payload||{} });
    try{
      if (navigator.sendBeacon) {
        navigator.sendBeacon(TRACK_URL, new Blob([body], {type:"application/json"}));
      } else {
        await fetch(TRACK_URL, {method:"POST", headers:{ "Content-Type":"application/json" }, body});
      }
    }catch(_){}
  }

  document.addEventListener("DOMContentLoaded", ()=>{
    send("page_view", { path: location.pathname, title: document.title });
  });

  // استدعِ window.trackSearch(value) بعد كل بحث
  window.trackSearch = (q)=> send("search", { q: String(q||"").trim(), page: location.pathname });
})();
