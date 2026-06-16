const CACHE="539-mobile-20260616001936";
async function clearAllCaches(){
  const keys=await caches.keys();
  await Promise.all(keys.map(key=>caches.delete(key)));
}
self.addEventListener("install",event=>{self.skipWaiting();event.waitUntil(clearAllCaches());});
self.addEventListener("activate",event=>{event.waitUntil(clearAllCaches().then(()=>self.clients.claim()));});
self.addEventListener("fetch",event=>{
  const req=event.request;
  if(req.method!=="GET") return;
  event.respondWith(fetch(req,{cache:"no-store"}));
});