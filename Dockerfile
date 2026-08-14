# F149：docker compose up 在乾淨機器（無 Python/node）上把 lift-log 跑起來。
# 只裝執行期依賴（--no-dev 排除 Playwright/Android 那組 dev 依賴）。
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH"

# 先只複製依賴宣告，讓依賴層在 app/ 程式碼變動時仍能吃快取
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
