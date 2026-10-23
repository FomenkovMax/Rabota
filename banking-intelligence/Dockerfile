FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install .
COPY alembic.ini ./
COPY migrations ./migrations
COPY config ./config
# Секреты в образ не копируются: .env подключается только через docker compose.
CMD ["bankintel", "bot"]
