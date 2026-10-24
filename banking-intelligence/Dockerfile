FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# WeasyPrint (PDF) требует Pango и шрифты с кириллицей
RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install .
COPY alembic.ini ./
COPY migrations ./migrations
COPY config ./config
COPY certs ./certs
ENV CONFIG_DIR=/app/config EXTRA_CA_BUNDLE=/app/certs/russian_trusted_root_ca.pem
# Секреты в образ не копируются: .env подключается только через docker compose.
CMD ["bankintel", "bot"]
