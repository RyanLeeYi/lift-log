#!/bin/bash
set -e
# 目標：全新 clone 或換機後，跑這一支就能到「可開發、可驗證」狀態

# 依賴
uv sync

# 本地 env（缺才複製，不覆蓋）
if [ ! -f .env ]; then
  cp .env.example .env
  echo "已建立 .env——請填入 LIFTLOG_TOKEN"
fi

# 煙霧測試：跑最小測試證明環境是活的
uv run pytest -q

echo "init OK"
