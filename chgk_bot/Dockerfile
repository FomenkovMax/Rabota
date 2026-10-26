# Один образ для бота и бэкенда (разные команды запуска в docker-compose.yml)
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN grep -viE 'pytest' requirements.txt > /tmp/req.txt && pip install --no-cache-dir -r /tmp/req.txt
COPY core ./core
COPY backend ./backend
COPY bot ./bot
COPY migrations ./migrations
COPY alembic.ini ./
COPY config ./config
COPY assets ./assets
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME /data
CMD ["python", "-m", "bot.main"]
