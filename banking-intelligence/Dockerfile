FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# WeasyPrint (PDF) требует Pango, шрифты с кириллицей и HarfBuzz-Subset (без него — предупреждение и устаревший обходной путь)
RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core fonts-liberation \
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
# Не root: процессы приложения работают от непривилегированного пользователя
RUN useradd --create-home --uid 10001 app && mkdir -p /data/raw && chown -R app /app /data
USER app
# Секреты в образ не копируются: .env подключается только через docker compose.
CMD ["bankintel", "bot"]
