"""Contraseñas (scrypt de la biblioteca estándar), validación de usuarios y freno a los intentos fallidos."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time

ROLES = ("admin", "user")
MIN_PASSWORD = 8
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(got, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


# Hash de relleno: al fallar el usuario se verifica contra él para no delatar por tiempo si existe.
_DUMMY = hash_password(secrets.token_hex(8))


def check_login(user: dict | None, password: str) -> bool:
    if user is None or not user["enabled"]:
        verify_password(password, _DUMMY)
        return False
    return verify_password(password, user["password_hash"])


def fingerprint(password_hash: str) -> str:
    """Huella guardada en la sesión: cambiar la contraseña cierra las sesiones abiertas."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def normalize_username(value: str) -> str:
    return (value or "").strip().lower()


def validate_username(username: str) -> str | None:
    if not _USERNAME.match(username):
        return "El usuario debe tener 3-32 caracteres: letras, números, punto, guion o guion bajo."
    return None


def validate_password(password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres."
    if len(password) > 200:
        return "La contraseña es demasiado larga."
    return None


class LoginThrottle:
    """Bloquea unos minutos un usuario tras varios fallos seguidos (en memoria: un solo worker)."""

    def __init__(self, max_fails: int = 5, window: int = 300):
        self.max_fails, self.window = max_fails, window
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        limit = time.time() - self.window
        recent = [t for t in self._fails.get(key, []) if t > limit]
        if recent:
            self._fails[key] = recent
        else:
            self._fails.pop(key, None)
        return recent

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key)) >= self.max_fails

    def fail(self, key: str):
        with self._lock:
            self._recent(key)
            self._fails.setdefault(key, []).append(time.time())

    def reset(self, key: str):
        with self._lock:
            self._fails.pop(key, None)
