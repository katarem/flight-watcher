"""Aerolíneas en estudio: todavía no son proveedores, pero la zona «Proveedores» comprueba si sus webs
dejan entrar a un cliente honesto (sin navegador y, si se pide, con Chromium headless) desde la IP del panel.

Solo se pide la portada (una petición por prueba y a mano): es lo justo para saber si hay anti-bot
antes de invertir en un proveedor. No se usan técnicas de sigilo. Binter y Air Europa no están: se
descartaron tras bloquear la IP (ver AGENTS.md).
"""
from __future__ import annotations

CANDIDATES: dict[str, dict] = {
    "volotea": {
        "label": "Volotea", "url": "https://www.volotea.com/es/",
        "notes": "Vuela muchas rutas nacionales directas. Sin API pública conocida.",
    },
    "easyjet": {
        "label": "easyJet", "url": "https://www.easyjet.com/es/",
        "notes": "Bases en BCN, MAD, PMI y AGP. Sin API pública conocida.",
    },
    "iberia": {
        "label": "Iberia", "url": "https://www.iberia.com/es/",
        "notes": "El 2026-09-30 respondía 403 a Chromium headless y solo tenía rutas con escala desde SVQ a TCI.",
    },
}

#: Huellas de anti-bot en cabeceras y cuerpo de la respuesta → nombre para el informe.
ANTIBOT_MARKS = (
    ("cf-ray", "Cloudflare"), ("just a moment", "Cloudflare"), ("cf-chl", "Cloudflare"),
    ("akamai", "Akamai"), ("_abck", "Akamai"), ("incapsula", "Imperva"), ("x-iinfo", "Imperva"),
    ("datadome", "DataDome"), ("kpsdk", "Kasada"), ("perimeterx", "PerimeterX"), ("_px", "PerimeterX"),
    ("captcha", "CAPTCHA"),
)


def antibot(headers: dict, body: str) -> list[str]:
    text = (" ".join(f"{k}:{v}" for k, v in headers.items()) + " " + body[:20000]).lower()
    return sorted({name for mark, name in ANTIBOT_MARKS if mark in text})
