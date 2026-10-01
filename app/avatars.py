"""Avatares de usuario: se guardan como archivos en DATA_DIR/avatars (nombre aleatorio por subida)."""
from __future__ import annotations

import secrets

from .config import AVATAR_DIR

MAX_BYTES = 2 * 1024 * 1024
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def sniff(data: bytes) -> str | None:
    """Tipo real por los primeros bytes (no se confía en el nombre ni en el Content-Type). SVG no se admite."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def save(user_id: int, data: bytes) -> str:
    """Guarda la imagen y devuelve el nombre de archivo. ValueError con mensaje para el usuario si no vale."""
    if len(data) > MAX_BYTES:
        raise ValueError("El avatar no puede pesar más de 2 MB.")
    ext = sniff(data)
    if ext is None:
        raise ValueError("El avatar debe ser una imagen PNG, JPG, GIF o WebP.")
    name = f"u{user_id}-{secrets.token_hex(6)}.{ext}"
    (AVATAR_DIR / name).write_bytes(data)
    return name


def remove(name: str | None):
    if name and "/" not in name and "\\" not in name:
        (AVATAR_DIR / name).unlink(missing_ok=True)
