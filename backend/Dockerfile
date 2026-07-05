FROM python:3.12-slim

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl fonts-noto-cjk libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-optional.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-optional.txt
COPY app ./app
RUN mkdir -p /app/tmp/uploads /app/data /app/.model_cache

EXPOSE 8100
