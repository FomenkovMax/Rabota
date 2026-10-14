FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir $(grep -viE 'pytest' requirements.txt)
COPY bot ./bot
COPY assets ./assets
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME /data
CMD ["python", "-m", "bot.main"]
