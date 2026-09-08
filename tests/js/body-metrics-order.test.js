import assert from "node:assert/strict";
import test from "node:test";

// LocalStore.bodyMetrics() 回 date DESC，server 回 ASC；api.listBodyMetrics 在 native 路徑
// 要把順序統一成升冪，否則折線圖左新右舊（2026-09-08 實機回報）。
globalThis.Capacitor = {
  isNativePlatform: () => true,
  Plugins: {
    LocalStore: {
      initialize: async () => {},
      snapshot: async () => ({
        body_metrics: [
          { date: "2026-09-03", weight_kg: 80 },
          { date: "2026-09-01", weight_kg: 82 },
          { date: "2026-09-02", weight_kg: 81 },
        ],
      }),
    },
  },
};
globalThis.localStorage ??= { getItem: () => null, setItem() {}, removeItem() {} };

const { api } = await import("../../app/static/js/api.js");

test("native listBodyMetrics returns rows in ascending date order", async () => {
  const rows = await api.listBodyMetrics({ from: "2026-09-01", to: "2026-09-30" });
  assert.deepEqual(rows.map((r) => r.date), ["2026-09-01", "2026-09-02", "2026-09-03"]);
});
