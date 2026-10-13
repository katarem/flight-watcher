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
LABEL org.opencontainers.image.title="Trip Watch" \
      org.opencontainers.image.description="Panel y bot que vigila precios de viajes (hoy, vuelos) y avisa por Discord y Telegram" \
      org.opencontainers.image.source="https://github.com/katarem/trip-watch" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DATA_DIR=/data \
    TZ=Europe/Madrid

WORKDIR /srv
COPY requirements.txt .
# patchright (Playwright parcheado) con Google Chrome, y Xvfb: una pantalla virtual para abrir Chrome «con ventana»
# sin monitor (lo usan las medidas anti-bot de los proveedores; ver app/providers/browser.py). Las fuentes DejaVu son
# las del calendario en PNG de los avisos (app/images.py).
RUN pip install -r requirements.txt \
    && patchright install --with-deps chrome \
    && apt-get update && apt-get install -y --no-install-recommends xvfb fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY --from=web /src/app/web ./app/web

VOLUME /data
EXPOSE 8000
ENV DISPLAY=:99
# La pantalla virtual en segundo plano y, con exec, uvicorn como proceso principal (recibe las señales de parada).
# Un único worker: el planificador vive dentro del proceso.
CMD ["sh", "-c", "Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 & exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
