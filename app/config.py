"""Rutas y conexión a la base de datos, leídas de variables de entorno."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR = DATA_DIR / "debug"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# Motor de base de datos: sqlite (por defecto, archivo en DATA_DIR), postgres, mysql o mariadb.
# Con `or` y no con el valor por defecto de getenv: docker compose pasa las variables vacías como "".
DB_ENGINE = (os.getenv("DB_ENGINE") or "sqlite").strip().lower()
DB_PATH = DATA_DIR / "flight_watcher.db"  # solo SQLite
DB_HOST = os.getenv("DB_HOST") or "localhost"
DB_PORT = int(os.getenv("DB_PORT") or (5432 if DB_ENGINE == "postgres" else 3306))
DB_NAME = os.getenv("DB_NAME") or "flight_watcher"
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
