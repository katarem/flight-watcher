# Etapa 1: compila el panel (React + Vite) a estáticos.
FROM node:22-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# vite.config.ts escribe el build en ../app/web
RUN npm run build

# Etapa 2: la app de Python (API + planificador) sirve el panel ya compilado.
FROM python:3.12-slim

ARG VERSION=dev
LABEL org.opencontainers.image.title="Flight Watcher" \
      org.opencontainers.image.description="Panel y bot que vigila precios de vuelos y avisa por Discord y Telegram" \
      org.opencontainers.image.source="https://github.com/katarem/flight-watcher" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DATA_DIR=/data \
    TZ=Europe/Madrid

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt && playwright install --with-deps chromium

COPY app ./app
COPY --from=web /src/app/web ./app/web

VOLUME /data
EXPOSE 8000
# Un único worker: el planificador vive dentro del proceso.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
