# Радар ЛНР — образ бота. Сборка: docker compose build
FROM python:3.13-slim

# Системные библиотеки для генерации PDF (WeasyPrint) и шрифты с кириллицей
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# uv — быстрый установщик зависимостей (тот же, что и при разработке)
RUN pip install --no-cache-dir uv==0.11.32

ENV RADAR_HOME=/app \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Сначала зависимости (этот слой кэшируется, пока не меняются pyproject.toml/uv.lock)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Затем код и конфиги
COPY src ./src
COPY config ./config
COPY channels.yaml ./channels.yaml
RUN uv sync --frozen --no-dev

# Не root: пользователь с uid 10001. Папку /data на сервере нужно отдать ему (делает vps_setup.sh)
RUN useradd --uid 10001 --create-home radar && mkdir -p /data && chown -R radar /data
USER radar

CMD ["python", "-m", "radar", "bot"]
