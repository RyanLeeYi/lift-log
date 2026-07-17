// lift-log service worker：app shell 快取（stale-while-revalidate）。
// /api/* 一律走網路不快取——寫入靠前端 IndexedDB 佇列緩衝（js/queue.js），server 是 SSOT。

// ⚠ 任何 SHELL 內資產（js/css/html）有改動就要遞增版本——否則既有安裝
// 會拿快取舊檔，新舊資產混版（sw.js 沒變 byte，瀏覽器不會重跑 install）
const CACHE_NAME = "liftlog-shell-v3";
const SHELL = [
  "/",
  "/css/app.css",
  "/js/api.js",
  "/js/app.js",
  "/js/body.js",
  "/js/calendar.js",
  "/js/dom.js",
  "/js/queue.js",
  "/js/state.js",
  "/js/templates.js",
  "/manifest.webmanifest",
  "/icon.svg",
];

self.addEventListener("install", (event) => {
  // 逐檔快取：單一檔案失敗不整包放棄（漏掉的執行期 fetch handler 會補）
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => Promise.allSettled(SHELL.map((url) => cache.add(url))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.startsWith("/api")) return;

  // stale-while-revalidate：先回快取（離線可用），背景更新下次生效
  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const cached = await cache.match(event.request);
      const refresh = fetch(event.request)
        .then((resp) => {
          if (resp.ok) cache.put(event.request, resp.clone());
          return resp;
        })
        // 離線且無快取：回明確的網路錯誤 Response（respondWith 不接受 undefined）
        .catch(() => cached || Response.error());
      if (cached) {
        // 背景更新掛進 waitUntil——否則 SW 可能在 revalidate 完成前被回收，殼永遠不更新
        event.waitUntil(refresh);
        return cached;
      }
      return refresh;
    }),
  );
});
