const CACHE_NAME='first-ai-agent-v1';
const URLS=['/','/scan','/manifest.webmanifest','/icon.svg'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE_NAME).then(c=>c.addAll(URLS)));self.skipWaiting();});
self.addEventListener('activate',e=>{e.waitUntil(self.clients.claim());});
self.addEventListener('fetch',e=>{
 const req=e.request;
 if(req.method!=='GET') return;
 e.respondWith(caches.match(req).then(r=>r||fetch(req).then(resp=>{const copy=resp.clone();caches.open(CACHE_NAME).then(c=>c.put(req,copy));return resp;}).catch(()=>caches.match('/scan'))));
});