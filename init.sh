#!/bin/bash
set -e
# 目標：全新 clone 或換機後，跑這一支就能到「可開發、可驗證」狀態

# 依賴
uv sync

# E2E 瀏覽器（前端 PWA 驗收用；playwright 已是 dev 依賴，這裡補瀏覽器二進位）
# 失敗不致命——後端開發不需要；前端 E2E 前補跑 `uv run playwright install chromium` 即可
uv run playwright install chromium || echo "⚠ chromium 安裝失敗——前端 E2E 需要，之後補跑：uv run playwright install chromium"

# 本地 env（缺才複製，不覆蓋）
if [ ! -f .env ]; then
  cp .env.example .env
  echo "已建立 .env——請填入 LIFTLOG_TOKEN"
fi

# 煙霧測試：跑最小測試證明環境是活的
uv run pytest -q

echo "init OK"
