// lift-log service worker：app shell 快取（stale-while-revalidate）。
// /api/* 一律走網路不快取——寫入靠前端 IndexedDB 佇列緩衝（js/queue.js），server 是 SSOT。

// ⚠ 任何 SHELL 內資產（js/css/html）有改動就要遞增版本——否則既有安裝
// 會拿快取舊檔，新舊資產混版（sw.js 沒變 byte，瀏覽器不會重跑 install）
const CACHE_NAME = "liftlog-shell-v87"; // F83：今日菜單改版（改此處務必同步 state.js 的 APP_VERSION）（改此處務必同步 state.js 的 APP_VERSION）
const SHELL = [
  "/",
  "/css/app.css",
  "/js/api.js",
  "/js/app-update.js",
  "/js/app.js",
  "/js/body.js",
  "/js/calendar.js",
  "/js/custom-exercise.js",
  "/js/dom.js",
  "/js/icons.js",
  "/js/env.js",
  "/js/exercise-detail.js",
  "/js/native-notify.js",
  "/js/push.js",
  "/js/queue.js",
  "/js/rest-notify.js",
  "/js/state.js",
  "/js/templates.js",
  "/manifest.webmanifest",
  "/icon.svg",
  // F79：字型也是 shell 的一部分——離線時載不到就整頁掉回系統字
  "/fonts/archivo-var.woff2",
  "/fonts/notosanstc-var.woff2",
  "/fonts/plexmono-400.woff2",
  "/fonts/plexmono-500.woff2",
  "/fonts/plexmono-600.woff2",
];

self.addEventListener("install", (event) => {
  // 逐檔快取：單一檔案失敗不整包放棄（漏掉的執行期 fetch handler 會補）。
  // ?v= 版本戳讓 CDN／瀏覽器快取的 key 必失效——新 SW 絕不裝到舊資產（F14 混版教訓）；
  // 回應以原始 URL 存入，fetch handler 才對得到
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) =>
        Promise.allSettled(
          SHELL.map(async (url) => {
            const resp = await fetch(`${url}?v=${CACHE_NAME}`, { cache: "reload" });
            if (!resp.ok) throw new Error(`${url}: ${resp.status}`);
            await cache.put(url, resp);
          }),
        ),
      )
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

// F31 Web Push：後端在休息到點時推來，顯示通知（可在其他 app 時收到）
self.addEventListener("push", (event) => {
  let data = { title: "休息結束", body: "時間到，繼續下一組！" };
  try {
    if (event.data) data = event.data.json();
  } catch {
    /* payload 壞掉：用預設文字 */
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      tag: "liftlog-rest", // 同 tag 取代舊的休息通知，不堆疊
      renotify: true,
      vibrate: [200, 100, 200],
      icon: "/icon.svg",
      badge: "/icon.svg",
    }),
  );
});

// 點通知：聚焦已開的分頁，否則開新視窗
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      const open = clients.find((c) => "focus" in c);
      return open ? open.focus() : self.clients.openWindow("/");
    }),
  );
});
