# 公開 URL（Render）で動かすための形。手元で試すときは README の uv の手順を使う
FROM python:3.14-slim
# 店の時刻（来店・お知らせの記録）を日本時間で残す
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
ENV TZ=Asia/Tokyo
COPY --from=ghcr.io/astral-sh/uv:0.11.27 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

# 依存だけ先に入れる（コードを変えても、ここは作り直さない）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# 台帳（data/ledger.db）は data/ に置く。Render では data/ に消えないディスクを付ける。無ければ初めての起動で見本を作る
# 分析は裏の処理で数分動くので、プロセスは1つ（--workers を増やさない）
CMD ["sh", "-c", "uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*'"]
