const CACHE="539-mobile-20260615232748";
self.addEventListener("install",event=>{self.skipWaiting();event.waitUntil(caches.open(CACHE));});
self.addEventListener("activate",event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim()));});
self.addEventListener("fetch",event=>{
  const req=event.request;
  if(req.method!=="GET") return;
  const url=new URL(req.url);
  if(url.pathname.endsWith("/")||url.pathname.endsWith("index.html")||url.pathname.endsWith(".json")||url.pathname.endsWith("prediction-history.html")){
    event.respondWith(fetch(req,{cache:"no-store"}).catch(()=>caches.match(req)));
    return;
  }
  event.respondWith(fetch(req).catch(()=>caches.match(req)));
});