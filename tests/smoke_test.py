"""Test de humo sin red ni navegador real: `python -m tests.smoke_test`

Sustituye el navegador y los proveedores por datos simulados y comprueba de extremo a extremo:
guardado de precios, reglas de aviso, enlaces con fecha, mensajes, la API del panel (sesión, permisos,
vigilancias, gráficas, canales, usuarios, ajustes), lugares y cobertura de rutas, escalas y monedas, la
revalidación semanal, los proveedores (incluidos, scripts, prueba con consola, exportar e importar paquetes y
prueba de acceso), los viajes de ida y vuelta y que el servidor entrega el panel compilado.
"""
import base64
import os
import sqlite3
import tempfile
import threading
import time
import json
import requests
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="fw-test-")
os.environ["PANEL_USER"], os.environ["PANEL_PASSWORD"] = "admin", "clave-de-prueba-1"
# Un «build» mínimo del panel para comprobar cómo se sirve (sin depender de Node).
WEB = Path(tempfile.mkdtemp(prefix="fw-web-"))
(WEB / "assets").mkdir()
(WEB / "index.html").write_text('<!doctype html><div id="root"></div>')
(WEB / "assets" / "app-1234.js").write_text("console.log(1)")
(WEB / "favicon.svg").write_text("<svg/>")
os.environ["WEB_DIR"] = str(WEB)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import checker, config, coverage, db, fx, health, places, trips  # noqa: E402
from app.main import app  # noqa: E402
from app.providers import PROVIDERS, DayPrice, link_for  # noqa: E402
from app.providers.base import Provider  # noqa: E402
from app.providers.extract import parse_day, parse_price, walk_json  # noqa: E402
from app.providers import browser, bundle, scripted, stealth  # noqa: E402

from . import fakes  # noqa: E402
from .fakes import ASKED, SENT, TARGETS, TODAY  # noqa: E402

fakes.install()

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==")
CSRF = {"X-Requested-With": "flight-watcher"}


def check(cond, msg):
    print(("  OK  " if cond else " FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


class Api:
    """Cliente de la API con su propia cookie de sesión (uno por usuario)."""

    def __init__(self, client: TestClient | None = None):
        self.c = client or TestClient(app)

    def req(self, method, path, **kw):
        return self.c.request(method, "/api/v1" + path, headers=CSRF, **kw)

    def get(self, path, **kw):
        return self.c.get("/api/v1" + path, **kw)

    def post(self, path, json=None, **kw):
        return self.req("POST", path, json=json if json is not None or "files" in kw else {}, **kw)

    def put(self, path, json):
        return self.req("PUT", path, json=json)

    def delete(self, path):
        return self.req("DELETE", path)

    def login(self, username, password):
        return self.post("/session", {"username": username, "password": password})


def errors(r) -> str:
    return "\n".join(r.json().get("errors", []))


def users_flow(admin: Api, admin_id: int):
    # --- CRUD de usuarios (solo admin)
    r = admin.get("/users")
    check(r.status_code == 200 and any(u["username"] == "admin" for u in r.json()["users"]), "lista de usuarios")
    bad = admin.post("/users", {"username": "A!", "password": "corta", "role": "user"})
    check(bad.status_code == 422 and "3-32 caracteres" in errors(bad) and "al menos 8" in errors(bad), "validación al crear usuario")
    bad = admin.post("/users", {"username": "ADMIN", "password": "una-clave-larga", "role": "user"})
    check("Ya existe" in errors(bad), "usuario duplicado (sin distinguir mayúsculas)")
    r = admin.post("/users", {"username": "Ana", "display_name": "Ana García", "password": "clave-de-ana-1",
                              "role": "user", "enabled": True})
    check(r.status_code == 201 and r.json()["user"]["username"] == "ana", "crear usuario")
    ana_id = r.json()["user"]["id"]
    check("password_hash" not in r.text, "la API nunca devuelve el hash")
    r = admin.post(f"/users/{ana_id}/avatar", files={"avatar": ("a.png", PNG, "image/png")})
    check(r.status_code == 200 and (r.json()["user"]["avatar"] or "").endswith(".png"), "subir el avatar de un usuario")
    with db.connect() as con:
        ana = db.get_user(con, ana_id)
    check(ana["role"] == "user" and ana["avatar"], "usuario y avatar guardados")
    got = admin.c.get(f"/avatars/{ana['avatar']}")
    check(got.status_code == 200 and got.content == PNG and got.headers["content-type"] == "image/png", "el avatar se sirve")
    check(any(u["avatar"] == ana["avatar"] for u in admin.get("/users").json()["users"]), "la lista incluye el avatar")
    check(admin.c.get("/avatars/..%2F..%2Fconfig.py").status_code == 404 and admin.c.get("/avatars/nope.png").status_code == 404,
          "avatar inexistente → 404 (sin salir de la carpeta)")
    check(TestClient(app).get(f"/avatars/{ana['avatar']}").status_code == 401, "los avatares exigen sesión")
    r = admin.post(f"/users/{ana_id}/avatar", files={"avatar": ("x.png", b"<svg onload=alert(1)/>", "image/png")})
    check(r.status_code == 422 and "debe ser una imagen" in errors(r), "un archivo que no es imagen se rechaza")
    with db.connect() as con:
        check(db.get_user(con, ana_id)["avatar"] == ana["avatar"], "el avatar anterior se conserva")

    # --- el usuario normal: sesión propia, sin acceso a lo de admin y con sus propias vigilancias
    ana_c = Api()
    check(ana_c.login("ana", "clave-de-ana-1").status_code == 200, "login de usuario normal")
    for path in ("/users", f"/users/{admin_id}", "/settings", "/debug/files", f"/users/{admin_id}/channels", "/providers"):
        check(ana_c.get(path).status_code == 403, f"{path} prohibido para un usuario normal")
    check(ana_c.post("/users", {"username": "x1x", "password": "12345678"}).status_code == 403, "crear usuarios prohibido")
    check(ana_c.put("/settings", {"schedule_hours": "1"}).status_code == 403, "cambiar ajustes prohibido")
    check(ana_c.post("/providers/health", {}).status_code == 403, "probar proveedores, solo admin")
    check(ana_c.get("/providers/vueling").status_code == 403 and ana_c.post("/providers/test", {}).status_code == 403
          and ana_c.get("/providers/export").status_code == 403 and ana_c.post("/providers/import", {}).status_code == 403,
          "editar, probar, exportar e importar proveedores, solo admin")
    watches = ana_c.get("/watches").json()["watches"]
    check(not watches, "no ve vigilancias ajenas")
    me = ana_c.get("/me").json()["user"]
    check(me["display_name"] == "Ana García" and me["role"] == "user" and "password_hash" not in me, "/me con sus datos")
    for path in ("/watches/1", "/watches/1/charts", "/watches/1/date-history?date=2026-01-01"):
        check(ana_c.get(path).status_code == 404, f"{path} de otro usuario → 404")
    check(ana_c.put("/watches/1", {"origin": "MAD", "destination": "BCN", "providers": ["vueling"]}).status_code == 404,
          "PUT de una vigilancia ajena → 404")
    for method, path in (("DELETE", "/watches/1"), ("POST", "/watches/1/toggle"), ("POST", "/watches/1/run")):
        check(ana_c.req(method, path).status_code == 404, f"{method} {path} de otro usuario → 404")
    check(admin.get("/watches/1").status_code == 200, "el dueño sigue accediendo")
    check(ana_c.get("/status").json()["current"] == "", "estado de ejecución sin nombres ajenos")

    r = ana_c.post("/watches", {"name": "Vigilancia de Ana", "origin": "MAD", "destination": "BCN",
                                "providers": ["mockweb"], "max_price": 100, "enabled": True})
    check(r.status_code == 201, "Ana crea su vigilancia")
    ana_watch = r.json()["watch"]
    with db.connect() as con:
        check(db.get_watch(con, ana_watch["id"])["user_id"] == ana_id, "la vigilancia pertenece a Ana")
    names = lambda c: [w["name"] for w in c.get("/watches").json()["watches"]]  # noqa: E731
    check("Vigilancia de Ana" in names(ana_c) and "Vigilancia de Ana" not in names(admin), "cada uno ve solo las suyas")
    check(admin.get(f"/watches/{ana_watch['id']}").status_code == 404, "ni el admin ve la de Ana")

    # --- canales de aviso: lista por usuario, varios tipos, validación y secretos
    kinds = {k["key"]: k for k in ana_c.get("/meta").json()["channel_kinds"]}
    check({"discord", "telegram"} <= set(kinds) and kinds["telegram"]["fields"][0]["secret"], "tipos de canal en /meta")
    bad = ana_c.post("/channels", {"kind": "discord", "name": "x", "config": {"webhook": "https://evil.example/hook"}})
    check("webhook de Discord no es válida" in errors(bad), "validación del webhook de Discord")
    bad = ana_c.post("/channels", {"kind": "telegram", "config": {"token": "x", "chat_id": "hola"}})
    check("token del bot" in errors(bad) and "chat ID" in errors(bad), "validación de Telegram")
    check(ana_c.post("/channels", {"kind": "sms"}).status_code == 400, "tipo de canal desconocido")
    for body in ({"kind": "discord", "name": "Mi Discord", "config": {"webhook": "https://discord.com/api/webhooks/2/ana"}},
                 {"kind": "discord", "name": "Discord del grupo", "config": {"webhook": "https://discord.com/api/webhooks/3/grupo"}},
                 {"kind": "telegram", "name": "Mi Telegram", "config": {"token": "123456:ABCDEFGHIJKLMNOPQRSTUVWX", "chat_id": "42"}}):
        r = ana_c.post("/channels", body)
        secret = body["config"].get("webhook") or body["config"]["token"]
        check(r.status_code == 201 and secret not in r.text,
              f"Ana añade el canal «{body['name']}» (la respuesta no lleva secretos)")
    r = ana_c.get("/channels")
    chans = {c["name"]: c for c in r.json()["channels"]}
    check(set(chans) == {"Mi Discord", "Discord del grupo", "Mi Telegram"}, "un usuario puede tener varios canales, también del mismo tipo")
    check("webhooks/2/ana" not in r.text and "ABCDEFGH" not in r.text and "config" not in r.text, "la lista de canales no muestra secretos")
    r = ana_c.get(f"/channels/{chans['Mi Discord']['id']}")
    field = r.json()["channel"]["fields"][0]
    check("webhooks/2/ana" not in r.text and field["saved"] and field["value"] == "", "ni siquiera al editar vuelve el secreto")
    r = ana_c.get(f"/channels/{chans['Mi Telegram']['id']}").json()["channel"]["fields"]
    check(r[1]["key"] == "chat_id" and r[1]["value"] == "42", "los campos no secretos sí vuelven")
    ana_c.put(f"/channels/{chans['Mi Discord']['id']}", {"name": "Mi Discord", "enabled": True, "config": {"webhook": ""}})
    with db.connect() as con:
        check(db.get_channel(con, chans["Mi Discord"]["id"])["config"]["webhook"].endswith("/2/ana"), "secreto vacío = se conserva el guardado")
    check(ana_c.post(f"/channels/{chans['Mi Telegram']['id']}/test").status_code == 200 and "Mi Telegram" in TARGETS[-1],
          "mensaje de prueba a un canal")

    # --- asignar canales a cada vigilancia
    ids = {n: c["id"] for n, c in chans.items()}
    with db.connect() as con:
        admin_chan_id = db.list_channels(con, admin_id)[0]["id"]
    form = {"name": "Vigilancia de Ana", "origin": "MAD", "destination": "BCN", "providers": ["mockweb"],
            "max_price": "100", "enabled": True}
    r = ana_c.put(f"/watches/{ana_watch['id']}", {**form, "channel_ids": [ids["Mi Discord"], admin_chan_id]})
    check(r.status_code == 200 and r.json()["watch"]["channel_ids"] == [ids["Mi Discord"]], "un canal ajeno no se puede asignar")
    SENT.clear(); TARGETS.clear()
    checker.run_checks(user_id=ana_id, trigger="manual")
    check(len(SENT) == 1 and TARGETS == [("Mi Discord",)] and "Vigilancia de Ana" in "\n".join(SENT[0][0]),
          "el aviso va solo al canal asignado a la vigilancia")
    with db.connect() as con:  # varios canales a la vez; uno pausado no recibe
        db.set_watch_channels(con, ana_watch["id"], [ids["Mi Discord"], ids["Mi Telegram"], ids["Discord del grupo"]])
        con.execute(text("DELETE FROM alerts WHERE watch_id = :w"), {"w": ana_watch["id"]})
    ana_c.put(f"/channels/{ids['Discord del grupo']}", {"name": "Discord del grupo", "enabled": False, "config": {"webhook": ""}})
    SENT.clear(); TARGETS.clear()
    checker.run_checks(user_id=ana_id, trigger="manual")
    check(TARGETS == [("Mi Discord", "Mi Telegram")], "avisa a todos los canales asignados y activos (el pausado, no)")
    with db.connect() as con:
        con.execute(text("DELETE FROM alerts WHERE watch_id = :w"), {"w": ana_watch["id"]})
        db.set_watch_channels(con, ana_watch["id"], [])
    SENT.clear(); TARGETS.clear()
    checker.run_checks(user_id=ana_id, trigger="manual")
    check(not SENT, "sin canales asignados no se avisa")
    SENT.clear(); TARGETS.clear()
    checker.run_checks(user_id=admin_id, trigger="manual")
    check(all(t == ("Discord admin",) for t in TARGETS) and not any("Vigilancia de Ana" in "\n".join(m[0]) for m in SENT),
          "las rondas por usuario no mezclan vigilancias ni canales")
    admin_cards = admin.get("/watches").json()["watches"]
    ana_cards = ana_c.get("/watches").json()["watches"]
    check(admin_cards[0]["channels"] == ["Discord admin"] and ana_cards[0]["channels"] == [],
          "el panel indica a qué canales avisa cada vigilancia")

    # --- aislamiento de canales entre usuarios
    check(ana_c.get(f"/channels/{admin_chan_id}").status_code == 404, "no se puede abrir un canal ajeno")
    check(ana_c.put(f"/channels/{admin_chan_id}", {"name": "x"}).status_code == 404, "ni editarlo")
    check(ana_c.delete(f"/channels/{admin_chan_id}").status_code == 404, "ni borrarlo")
    check(ana_c.post(f"/channels/{admin_chan_id}/test").status_code == 404, "ni probarlo")
    check(ana_c.post(f"/users/{ana_id}/channels", {"kind": "discord"}).status_code == 403, "las rutas de canales de admin están protegidas")

    # --- el admin gestiona los canales de un usuario
    r = admin.get(f"/users/{ana_id}/channels")
    check("Mi Telegram" in r.text and "ABCDEFGH" not in r.text, "el admin ve los canales del usuario (sin secretos)")
    r = admin.post(f"/users/{ana_id}/channels", {"kind": "discord", "name": "Puesto por el admin", "enabled": True,
                                                 "config": {"webhook": "https://discord.com/api/webhooks/4/admin-para-ana"}})
    check(r.status_code == 201, "el admin crea un canal para Ana")
    made = r.json()["channel"]["id"]
    check("Puesto por el admin" in ana_c.get("/channels").text, "Ana lo ve en su perfil")
    admin.put(f"/users/{ana_id}/channels/{made}", {"name": "Renombrado", "enabled": True, "config": {"webhook": ""}})
    with db.connect() as con:
        c = db.get_channel(con, made)
    check(c["name"] == "Renombrado" and c["config"]["webhook"].endswith("admin-para-ana"), "el admin edita el canal y conserva el secreto")
    check(admin.put(f"/users/{admin_id}/channels/{made}", {"name": "x"}).status_code == 404,
          "…solo dentro del usuario indicado en la URL")
    check(admin.post(f"/users/{ana_id}/channels/{made}/test").status_code == 200, "el admin prueba el canal")
    check(admin.delete(f"/users/{ana_id}/channels/{made}").status_code == 204, "el admin elimina el canal")
    with db.connect() as con:
        check(db.get_channel(con, made) is None, "…y desaparece")
    ana_c.delete(f"/channels/{ids['Mi Discord']}")
    with db.connect() as con:
        db.set_watch_channels(con, ana_watch["id"], [ids["Mi Telegram"]])
    check(ana_c.delete(f"/channels/{ids['Mi Telegram']}").status_code == 204, "Ana borra un canal")
    check(ana_c.get(f"/watches/{ana_watch['id']}").json()["watch"]["channel_ids"] == [],
          "borrar un canal lo quita de las vigilancias que lo usaban")
    r = ana_c.put("/profile", {"display_name": "Ana G.", "notify_errors": False})
    check(r.json()["user"]["display_name"] == "Ana G." and r.json()["user"]["notify_errors"] is False, "guardar el perfil")
    r = ana_c.post("/profile/avatar", files={"avatar": ("b.png", PNG, "image/png")})
    new_avatar = r.json()["user"]["avatar"]
    check(r.status_code == 200 and new_avatar != ana["avatar"] and not (config.AVATAR_DIR / ana["avatar"]).exists(),
          "cambiar el avatar propio borra el anterior")
    ana["avatar"] = new_avatar

    # --- contraseña propia: las demás sesiones se cierran
    other = Api()
    other.login("ana", "clave-de-ana-1")
    bad = ana_c.post("/profile/password", {"current_password": "mal", "new_password": "nueva-clave-9", "confirm_password": "otra"})
    check("actual no es correcta" in errors(bad) and "no coincide" in errors(bad), "validación del cambio de contraseña")
    r = ana_c.post("/profile/password", {"current_password": "clave-de-ana-1", "new_password": "nueva-clave-9",
                                          "confirm_password": "nueva-clave-9"})
    check(r.status_code == 200 and ana_c.get("/me").status_code == 200, "la sesión que cambia la clave sigue activa")
    check(other.get("/me").status_code == 401, "las demás sesiones se cierran al cambiar la clave")
    check(Api().login("ana", "clave-de-ana-1").status_code == 401, "la clave vieja ya no vale")

    # --- reglas de seguridad del CRUD
    r = admin.delete(f"/users/{admin_id}")
    check(r.status_code == 422 and "propia" in errors(r), "el admin no puede borrarse a sí mismo")
    admin.put(f"/users/{admin_id}", {"username": "admin", "role": "user", "enabled": False})
    with db.connect() as con:
        check(db.get_user(con, admin_id)["role"] == "admin" and db.get_user(con, admin_id)["enabled"], "el admin no puede quitarse el rol ni desactivarse")
    r = admin.put(f"/users/{ana_id}", {"username": "ana", "display_name": "Ana", "role": "admin", "enabled": True})
    check(r.status_code == 200 and ana_c.get("/users").status_code == 200, "ascender a admin")
    ana_c.put(f"/users/{admin_id}", {"username": "admin", "role": "user", "enabled": True})
    with db.connect() as con:
        check(db.get_user(con, admin_id)["role"] == "user" and db.count_admins(con) == 1, "otro admin puede cambiar el rol")
    old_admin = Api()
    old_admin.login("admin", "clave-de-prueba-1")
    check(old_admin.get("/users").status_code == 403, "el degradado ya no es admin")
    ana_c.put(f"/users/{ana_id}", {"username": "ana", "role": "user", "enabled": False})
    with db.connect() as con:
        check(db.get_user(con, ana_id)["role"] == "admin" and db.get_user(con, ana_id)["enabled"],
              "nadie puede degradarse o desactivarse a sí mismo (queda siempre un admin)")
    ana_c.put(f"/users/{admin_id}", {"username": "admin", "role": "admin", "enabled": True})

    # --- desactivar: pierde la sesión y sus vigilancias dejan de comprobarse
    admin.put(f"/users/{ana_id}", {"username": "ana", "role": "user", "enabled": False})
    check(ana_c.get("/me").status_code == 401, "usuario desactivado: sesión cerrada")
    check(Api().login("ana", "nueva-clave-9").status_code == 401, "usuario desactivado: no puede entrar")
    check(checker.run_checks(user_id=ana_id, trigger="manual") == "empty", "sus vigilancias no se comprueban")

    # --- eliminar usuario: se lleva sus vigilancias y su avatar
    avatar_path = config.AVATAR_DIR / ana["avatar"]
    check(avatar_path.exists(), "el archivo del avatar existe")
    check(admin.delete(f"/users/{ana_id}").status_code == 204, "eliminar usuario")
    with db.connect() as con:
        check(db.get_user(con, ana_id) is None and db.get_watch(con, ana_watch["id"]) is None, "se borra el usuario y sus vigilancias")
        n = con.execute(text("SELECT count(*) FROM prices WHERE watch_id = :w"), {"w": ana_watch["id"]}).scalar()
    check(n == 0 and not avatar_path.exists(), "…con su histórico y su avatar")
    check(admin.delete("/session").status_code == 204 and admin.get("/me").status_code == 401, "cerrar sesión")
    check(admin.login("admin", "clave-de-prueba-1").status_code == 200, "volver a entrar")


def trips_flow(admin: Api, admin_chan: int):
    # Vigilancias iniciales: 1 = SVQ→TCI, 2 = TCI→SVQ. Los dobles dan precio los días +10, +11 y +12; el más
    # barato de cada día entre Vueling y Ryanair es 55, 30 y 70 € en los dos sentidos.
    d10, d11, d12 = ((TODAY + timedelta(days=n)).isoformat() for n in (10, 11, 12))
    bad = admin.post("/trips", {})
    check(bad.status_code == 422 and "vigilancia de ida" in errors(bad) and "vigilancia de vuelta" in errors(bad),
          "viaje: hay que elegir las dos vigilancias")
    bad = admin.post("/trips", {"outbound_id": 1, "return_id": 1, "min_nights": "5", "max_nights": "2"})
    check("distintas" in errors(bad) and "no pueden ser más" in errors(bad), "viaje: tramos distintos y noches coherentes")
    bad = admin.post("/trips", {"outbound_id": 1, "return_id": 2, "min_nights": "0", "max_nights": "99"})
    check("entre 1 y 60" in errors(bad), "viaje: noches fuera de rango")
    r = admin.post("/trips", {"outbound_id": 1, "return_id": "2", "min_nights": 1, "max_nights": 2, "max_total": "90",
                              "channel_ids": [admin_chan]})
    trip = r.json()["trip"]
    check(r.status_code == 201 and trip["name"] == "SVQ ⇄ TCI" and trip["warnings"] == []
          and trip["outbound"]["origin"] == "SVQ" and trip["return"]["origin"] == "TCI", "crear un viaje con dos vigilancias")
    tid = trip["id"]

    # --- combinaciones con los precios actuales (sin consultar ninguna web)
    card = {t["id"]: t for t in admin.get("/trips").json()["trips"]}[tid]
    best = card["best"]
    check(best["out_date"] == d10 and best["ret_date"] == d11 and best["nights"] == 1 and best["total"] == 85
          and best["deal"] == "fixed" and best["out"]["provider"] == "vueling" and best["out"]["route"] == "SVQ→TFN"
          and "d=TFN" in best["out"]["link"] and card["n_dates"] == 2, "el viaje más barato: ida + vuelta con sus enlaces")
    detail = admin.get(f"/trips/{tid}").json()
    check([(q["out_date"], q["nights"], q["total"]) for q in detail["quotes"]] == [(d10, 1, 85), (d11, 1, 100)],
          "la combinación más barata de cada fecha de ida")
    opts = admin.get(f"/trips/{tid}/options", params={"date": d10}).json()["options"]
    check([(o["nights"], o["total"]) for o in opts] == [(1, 85), (2, 125)], "todas las noches de una fecha de ida")
    with db.connect() as con:
        future = trips.local_now(db.get_settings()) + timedelta(days=trips.STALE_DAYS + 1)
        check(trips.legs_by_day(con, db.get_settings(), db.get_watch(con, 2), future) == {},
              "los precios viejos de un tramo no cuentan")

    # --- aviso del viaje: total, fechas y un enlace por tramo; una sola vez
    SENT.clear()
    checker.run_checks(trip_id=tid, trigger="manual")
    msgs = ["\n".join(m[0]) for m in SENT if "🧳" in m[0][0]]
    check(len(msgs) == 1 and "**85 €**" in msgs[0] and "1 noche" in msgs[0] and "ida [Vueling 55 € (SVQ→TFN)]" in msgs[0]
          and "vuelta [Vueling 30 € (TFN→SVQ)]" in msgs[0] and "100 €" not in msgs[0],
          "aviso del viaje con el total y un enlace por tramo (solo lo que cumple la regla)")
    html_msg = "\n".join(next(m[1] for m in SENT if "🧳" in m[0][0]))
    check('ida <a href="' in html_msg and "&amp;" in html_msg, "aviso del viaje en HTML para Telegram")
    with db.connect() as con:
        n_quotes = con.execute(text("SELECT count(*) FROM trip_quotes WHERE trip_id = :t"), {"t": tid}).scalar()
    check(n_quotes == 2, "se guarda la combinación más barata de cada fecha de ida")
    SENT.clear()
    checker.run_checks(trip_id=tid, trigger="manual")
    check(not any("🧳" in m[0][0] for m in SENT), "no repite el aviso de un viaje")

    # --- regla relativa sobre la mediana de los totales
    with db.connect() as con:
        old = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
        db.insert_trip_quotes(con, tid, old, [{"out_date": d12, "ret_date": d12, "total": 300, "out": {"price": 150},
                                                "ret": {"price": 150}}] * 40)
    form = {"outbound_id": 1, "return_id": 2, "min_nights": 1, "max_nights": 2, "max_total": "", "discount_pct": "50",
            "channel_ids": [admin_chan], "name": "Tenerife"}
    check(admin.put(f"/trips/{tid}", form).json()["trip"]["max_total"] is None, "editar el viaje")
    SENT.clear()
    checker.run_checks(trip_id=tid, trigger="manual")
    msgs = ["\n".join(m[0]) for m in SENT if "🧳" in m[0][0]]
    check(len(msgs) == 1 and "habitual ≈ 300 €" in msgs[0] and "**100 €**" in msgs[0] and "85 €" not in msgs[0],
          "regla relativa: avisa de la nueva fecha (la ya avisada no se repite)")
    check(admin.get(f"/trips/{tid}").json()["base"] == 300, "total habitual del viaje")

    # --- en las rondas: los viajes activos con algún tramo comprobado; los pausados, no
    def quotes():
        with db.connect() as con:
            return con.execute(text("SELECT count(*) FROM trip_quotes WHERE trip_id = :t"), {"t": tid}).scalar()
    before = quotes()
    checker.run_checks(watch_id=2, trigger="manual")
    check(quotes() == before + 2, "comprobar un tramo recalcula el viaje")
    check(admin.post(f"/trips/{tid}/toggle").json()["trip"]["enabled"] is False, "pausar un viaje")
    before = quotes()
    checker.run_checks(trigger="manual")
    check(quotes() == before, "un viaje en pausa no se recalcula en las rondas")
    admin.post(f"/trips/{tid}/toggle")
    detail = admin.get(f"/trips/{tid}").json()
    check(detail["trend"] and detail["alerts"][0]["total"] == 100, "evolución del total y avisos enviados")

    # --- tramos que no encajan, en pausa o borrados
    a = admin.post("/watches", {"origin": "MAD", "destination": "BCN", "providers": ["mockweb"]}).json()["watch"]
    other = admin.post("/trips", {"outbound_id": 1, "return_id": a["id"], "min_nights": 3, "max_nights": 3}).json()["trip"]
    check(len(other["warnings"]) == 2 and "La vuelta sale de MAD" in other["warnings"][0], "aviso si los tramos no encajan")
    admin.post(f"/watches/{a['id']}/toggle")
    check(any("en pausa" in w for w in admin.get(f"/trips/{other['id']}").json()["trip"]["warnings"]), "aviso si un tramo está en pausa")
    check(admin.get(f"/watches/{a['id']}").json()["trips"] == [{"id": other["id"], "name": "SVQ ⇄ TCI"}],
          "el detalle de una vigilancia dice de qué viajes es tramo")
    admin.delete(f"/watches/{a['id']}")
    check(admin.get(f"/trips/{other['id']}").status_code == 404, "borrar una vigilancia borra los viajes que la usan")

    # --- solo para su dueño
    admin.post("/users", {"username": "berta", "password": "clave-de-berta-1", "role": "user"})
    berta = Api()
    berta.login("berta", "clave-de-berta-1")
    check(not berta.get("/trips").json()["trips"], "no ve viajes ajenos")
    for method, path in (("GET", f"/trips/{tid}"), ("GET", f"/trips/{tid}/options?date={d10}"), ("PUT", f"/trips/{tid}"),
                         ("DELETE", f"/trips/{tid}"), ("POST", f"/trips/{tid}/toggle"), ("POST", f"/trips/{tid}/run")):
        check(berta.req(method, path, json=form if method == "PUT" else None).status_code == 404, f"{method} {path} ajeno → 404")
    bad = berta.post("/trips", {"outbound_id": 1, "return_id": 2})
    check(bad.status_code == 422 and "entre las tuyas" in errors(bad), "no se pueden usar vigilancias ajenas")
    with db.connect() as con:
        db.delete_user(con, db.get_user_by_username(con, "berta")["id"])
    return tid


def providers_flow(admin: Api, admin_id: int, admin_chan: int):
    # --- catálogo de lugares y autocompletado
    found = admin.get("/places", params={"q": "tenerife"}).json()["places"]
    check(found[0]["code"] == "TCI" and found[0]["kind"] == "city" and found[0]["airports"] == ["TFN", "TFS"],
          "autocompletado: la ciudad (TCI) antes que sus aeropuertos")
    check([p["code"] for p in admin.get("/places", params={"q": "malaga"}).json()["places"]][:1] == ["AGP"],
          "autocompletado sin tildes (malaga → Málaga)")
    check(admin.get("/places", params={"q": "canarias"}).json()["places"][0]["code"] == "canarias", "grupos propios")
    es = admin.get("/places/es").json()["place"]
    check(es["kind"] == "country" and es["label"] == "España" and "SVQ" in es["airports"], "países (con sus aeropuertos regulares)")
    check(admin.get("/places/XQZ").status_code == 404, "lugar desconocido → 404")
    check(places.routes("SVQ", "TCI") == [("SVQ", "TFN"), ("SVQ", "TFS")], "expansión de ciudades a aeropuertos")

    # --- comprobación de ruta al crear: en paralelo, con el motivo de los que no valen
    ASKED.clear()
    r = admin.post("/route-check", {"origin": "SVQ", "destination": "TCI"})
    res = {p["key"]: p for p in r.json()["providers"]}
    check(r.status_code == 200 and r.json()["pairs"] == ["SVQ-TFN", "SVQ-TFS"], "route-check expande origen y destino")
    check(res["vueling"]["ok"] and res["vueling"]["routes"] == ["SVQ-TFN"] and res["ryanair"]["routes"] == ["SVQ-TFS"],
          "cada proveedor dice qué pares opera (Vueling → TFN, Ryanair → TFS)")
    check(res["wizzair"]["status"] == "none" and "no tiene vuelos directos" in res["wizzair"]["reason"],
          "…y por qué no vale el que no la opera")
    check(res["google"]["ok"] and res["google"]["coverage"] == "universal" and len(res["google"]["routes"]) == 2,
          "Google Flights cubre cualquier ruta")
    asked = len(ASKED)
    admin.post("/route-check", {"origin": "SVQ", "destination": "TCI"})
    check(len(ASKED) == asked, "la cobertura se guarda en caché (no se vuelve a preguntar)")
    r = admin.post("/route-check", {"origin": "andalucia", "destination": "canarias"})
    res = {p["key"]: p for p in r.json()["providers"]}
    check(res["google"]["status"] == "too_many" and "como mucho 12" in res["google"]["reason"], "límite de pares de Google Flights")
    bad = admin.post("/route-check", {"origin": "ES", "destination": "canarias"})
    check(bad.status_code == 422 and "combinaciones" in errors(bad), "demasiadas combinaciones de aeropuertos")

    def slow_probe(self, session, o, d):
        time.sleep(2)
        return True
    old_probe = type(PROVIDERS["vueling"]).probe
    type(PROVIDERS["vueling"]).probe = slow_probe
    started = time.monotonic()
    out = {x.key: x for x in coverage.check_many(["vueling", "ryanair"], [("MAD", "PMI")], timeout=0.5)}
    check(out["vueling"].status == "timeout" and out["ryanair"].status in ("ok", "none") and time.monotonic() - started < 1.5,
          "tiempo límite por proveedor (el lento no retrasa a los demás)")
    type(PROVIDERS["vueling"]).probe = old_probe

    # --- vigilancias con cobertura, escalas y monedas
    bad = admin.post("/watches", {"origin": "SVQ", "destination": "TCI", "providers": ["vueling", "wizzair"]})
    check(bad.status_code == 422 and "Wizz Air no opera esta ruta" in errors(bad), "no se guarda un proveedor que no opera la ruta")
    r = admin.post("/watches", {"name": "Barcelona → Budapest", "origin": "BCN", "destination": "BUD", "providers": ["wizzair"],
                                "max_price": "35", "max_stops": "0", "channel_ids": [admin_chan]})
    w = r.json()["watch"]
    check(r.status_code == 201 and w["coverage"][0]["routes"] == ["BCN-BUD"] and w["coverage"][0]["checked_at"]
          and w["origin_place"]["label"] == "Barcelona (BCN)" and w["max_stops"] == 0, "vigilancia con su cobertura comprobada")
    SENT.clear()
    checker.run_checks(watch_id=w["id"], trigger="manual")
    with db.connect() as con:
        snap = db.latest_snapshot(con, w["id"], "wizzair")
    check(snap[0]["price"] == 30 and snap[0]["orig_price"] == 12000 and snap[0]["currency"] == "HUF",
          "precio en moneda original y su equivalente en euros (cambio del BCE)")
    check(SENT and "12.000 HUF" in "\n".join(SENT[0][0]) and "30 €" in "\n".join(SENT[0][0]), "el aviso muestra euros y la moneda original")
    detail = admin.get(f"/watches/{w['id']}").json()
    check(detail["prices"][0]["currency"] == "HUF" and detail["stats"][0]["best"]["orig_price"] == 12000, "el panel recibe la moneda original")
    bad = admin.post("/watches", {"origin": "MAD", "destination": "BCN", "providers": ["google"], "max_stops": "7"})
    check("máximo de escalas" in errors(bad), "validación del máximo de escalas")

    g = admin.post("/watches", {"origin": "MAD", "destination": "BCN", "providers": ["google"], "max_stops": "0"}).json()["watch"]
    checker.run_checks(watch_id=g["id"], trigger="manual")
    with db.connect() as con:
        days = {r["flight_date"]: r for r in db.latest_snapshot(con, g["id"], "google")}
    check((TODAY + timedelta(days=11)).isoformat() not in days and len(days) == 2, "solo directos: el día con escala no cuenta")
    admin.put(f"/watches/{g['id']}", {"origin": "MAD", "destination": "BCN", "providers": ["google"], "max_stops": ""})
    checker.run_checks(watch_id=g["id"], trigger="manual")
    with db.connect() as con:
        snap = db.latest_snapshot(con, g["id"], "google")
    check(snap[0]["price"] == 70 and snap[0]["stops"] == 1, "sin límite de escalas: entra y se guarda cuántas tiene")
    admin.delete(f"/watches/{g['id']}")

    # --- un proveedor inactivo (ruta cerrada) no se consulta
    with db.connect() as con:
        db.update_watch_provider(con, 1, "ryanair", [], False, "2026-01-01T00:00:00")
        before = con.execute(text("SELECT count(*) FROM runs WHERE watch_id = 1 AND provider = 'ryanair'")).scalar()
    checker.run_checks(watch_id=1, trigger="manual")
    with db.connect() as con:
        after = con.execute(text("SELECT count(*) FROM runs WHERE watch_id = 1 AND provider = 'ryanair'")).scalar()
    card = {c["id"]: c for c in admin.get("/watches").json()["watches"]}[1]
    check(after == before and not {s["key"]: s for s in card["stats"]}["ryanair"]["active"],
          "un proveedor inactivo no se consulta y el panel lo marca")

    # --- revalidación semanal: la primera vez sin avisos; después avisa si una ruta se abre o se cierra
    with db.connect() as con:
        db.set_watch_providers(con, 1, db.default_coverage("SVQ", "TCI", ["vueling", "ryanair"]))
    SENT.clear()
    coverage.revalidate()
    with db.connect() as con:
        cov = db.get_watch(con, 1)["coverage"]
    check(cov["vueling"]["routes"] == [("SVQ", "TFN")] and cov["ryanair"]["routes"] == [("SVQ", "TFS")]
          and cov["ryanair"]["checked_at"] and not SENT, "primera revalidación: ajusta los pares sin avisar")
    fakes.OPERATES["ryanair"] = set()
    coverage.revalidate()
    with db.connect() as con:
        cov = db.get_watch(con, 1)["coverage"]
    msg = "\n".join(m for s in SENT for m in s[0])
    check(not cov["ryanair"]["active"] and "Ryanair: deja de operar SVQ→TFS" in msg and TARGETS[-1] == ("Discord admin",),
          "aviso al cerrarse una ruta de temporada (a los canales de la vigilancia)")
    r = admin.put("/watches/1", {"name": "Sevilla → Tenerife", "origin": "SVQ", "destination": "TCI",
                                 "providers": ["vueling", "ryanair"], "max_price": 40, "max_stops": 0, "channel_ids": [admin_chan]})
    check(r.status_code == 200 and {c["key"]: c for c in r.json()["watch"]["coverage"]}["ryanair"]["active"] is False,
          "al editar se conserva el proveedor de temporada (inactivo)")
    fakes.OPERATES["ryanair"] = {"TFS"}
    SENT.clear()
    coverage.revalidate()
    msg = "\n".join(m for s in SENT for m in s[0])
    check("Ryanair: se abre SVQ→TFS" in msg, "aviso al abrirse de nuevo")

    # --- una sola petición a la vez por proveedor y con pausa entre ellas
    class Slow(Provider):
        key, label, min_interval, jitter = "lento", "Lento", 0.15, 0

        def fetch_prices(self, *a, **k):
            return []
    prov, spans = Slow(), []

    def use():
        with prov.slot():
            start = time.monotonic()
            time.sleep(0.05)
            spans.append((start, time.monotonic()))
    threads = [threading.Thread(target=use) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    spans.sort()
    check(all(b[0] >= a[1] + 0.14 for a, b in zip(spans, spans[1:])), "turno por proveedor: sin solapes y con pausa")

    # --- prueba de acceso a los proveedores (solo admin)
    r = admin.post("/providers/health", {})
    res = {x["key"]: x for x in r.json()["results"]}
    check(r.status_code == 200 and set(res) >= {"vueling", "ryanair", "wizzair", "google"}
          and res["vueling"]["status"] == res["google"]["status"] == "ok", "prueba de acceso de todos los proveedores")
    check([s["name"] for s in res["ryanair"]["steps"]] == ["Cobertura", "Precios (1 mes)"]
          and "1 destino directo desde SVQ (no incluye BCN)" in res["ryanair"]["steps"][0]["detail"]
          and res["ryanair"]["status"] == "empty", "pasos: cobertura y precios (accesible pero sin precios en esa ruta)")
    check(res["google"]["steps"][0]["status"] == "skipped" and res["mockweb"]["steps"][1]["status"] == "skipped",
          "pasos que no aplican: omitidos sin estropear el resultado")
    check(r.json()["fx"]["status"] == "ok" and "BCE" in r.json()["fx"]["name"], "también el cambio de divisas")
    fakes.BLOCKED.add("wizzair")
    r = admin.post("/providers/health", {"providers": ["wizzair"], "origin": "bcn", "destination": "bud"})
    res = r.json()["results"][0]
    check(res["status"] == "blocked" and res["steps"][0]["http_status"] == 403 and len(res["steps"]) == 1,
          "un proveedor que bloquea sale como «bloqueado» y no se insiste")
    fakes.BLOCKED.clear()
    lst = admin.get("/providers").json()
    last = {p["key"]: p for p in lst["providers"]}
    check(last["wizzair"]["last"]["status"] == "blocked" and last["vueling"]["coverage"] == "probe"
          and last["google"]["stops_filter"] and not last["vueling"]["stops_filter"] and "candidates" not in lst,
          "último resultado guardado por proveedor")
    bad = admin.post("/providers/health", {"origin": "TCI", "destination": "SVQ"})
    check(bad.status_code == 422 and "aeropuerto" in errors(bad), "la ruta de prueba debe ser de aeropuertos")

    # --- piezas sueltas: funciones del script de Google Flights y cambio del BCE
    parse_response, request_body = PROVIDERS["google"].ns["parse_response"], PROVIDERS["google"].ns["request_body"]
    body = ")]}'\n\n123\n" + json.dumps([["wrb.fr", None, json.dumps(
        [None, [["2026-11-02", None, [[None, 54], "x"]], ["2026-11-03", None, [[None, 61.5], "y"]]]])]])
    check(parse_response(body) == {date(2026, 11, 2): 54, date(2026, 11, 3): 61.5}, "Google Flights: precios por día")
    check('[[[\\"SVQ\\",0]]]' in request_body("SVQ", "TFN", date(2026, 11, 1), date(2026, 12, 1), 0), "Google Flights: petición")
    try:
        parse_response("<html>consent</html>")
        check(False, "Google Flights: formato inesperado")
    except Exception as exc:  # noqa: BLE001
        check("formato inesperado" in str(exc), "Google Flights: un formato inesperado es un error claro")
    xml = "<Cube time='2026-10-09'><Cube currency='USD' rate='1.1012'/><Cube currency='HUF' rate='398.5'/></Cube>"
    check(fx.parse(xml) == {"date": "2026-10-09", "rates": {"USD": 1.1012, "HUF": 398.5}}, "lectura del XML del BCE")
    check(fx.to_eur(110, "USD") == 100 and fx.to_eur(5, "EUR") == 5, "conversión a euros")

# Web simulada para los proveedores propios: {url: (estado, cuerpo JSON)}; el resto responde 404.
HTTP: dict = {}


#: `timeout` con el que se hizo cada petición de FakeHttp.
WAITS: list = []


class FakeHttp:
    """Sustituye a requests.Session en los scripts: sin red, con las respuestas de HTTP."""
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def request(self, method, url, timeout=None, params=None, json=None):
        WAITS.append(timeout)
        answer = HTTP.get(url, (404, {"error": "no existe"}))
        if isinstance(answer, list):  # respuestas sucesivas; la última se repite
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        if answer == "timeout":
            raise requests.Timeout("sin respuesta")
        status, body = answer

        class Resp:
            pass
        r = Resp()
        r.url, r.status_code, r.ok = url, status, status < 400
        r.headers = {"content-type": "application/json"}
        r.text = __import__("json").dumps(body)
        r.json = lambda: body
        return r


SCRIPT = """
BASE = "https://api.prueba.test"


def network(api, origin):
    data = api.get_json(f"{BASE}/rutas/{origin}")
    return [] if data is None else data["destinos"]


def fetch_route(api, origin, destination, start, max_months):
    data = api.get_json(f"{BASE}/precios/{origin}/{destination}", meses=max_months)
    if data is None:
        return {}
    api.log("días recibidos:", len(data["dias"]))
    return [DayPrice(date.fromisoformat(d["fecha"]), d["precio"], currency=d.get("moneda", "EUR"))
            for d in data["dias"]]
"""


def run_test(admin: Api, body: dict):
    """Prueba del editor: (respuesta, resultado final, trazas de la consola) leyendo el NDJSON en streaming."""
    r = admin.post("/providers/test", body)
    if r.status_code != 200:
        return r, None, []
    events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
    return r, events[-1]["result"], events[:-1]


def console_text(events) -> str:
    return "\n".join(f"{e['level']}: {e['text']}" for e in events)


class FakeCurl:
    """Sustituye al cliente con la huella de Chrome (curl_cffi): apunta cada petición y responde de BLOCKS."""

    def __init__(self):
        self.headers, self.calls = {}, []

    def request(self, method, url, headers=None, timeout=None, **kw):
        self.calls.append((method, url, dict(headers or {}), kw))
        status = BLOCKS.get(url, 200)

        class Resp:
            pass
        r = Resp()
        r.url, r.status_code, r.ok, r.cookies = url, status, status < 400, {"__cf_bm": "x"}
        r.headers = {"content-type": "application/json" if status == 200 else "text/html"}
        r.text = '{"ok": true}' if status == 200 else "<html>Just a moment...</html>"
        r.json = lambda: {"ok": True}
        return r

    def close(self):
        pass


class FakeBrowser:
    """Sustituye a Chrome (browser.BrowserFetch): apunta las peticiones y si se cerró."""
    made: list = []

    def __init__(self, key, trace=None):
        self.key, self.calls, self.closed = key, [], False
        FakeBrowser.made.append(self)

    def request(self, site, method, url, **kw):
        self.calls.append((site, method, url))
        return browser.BrowserResponse({"status": 200, "url": url, "headers": {"Content-Type": "application/json"},
                                        "text": '{"desde": "chrome"}'})

    def close(self):
        self.closed = True


BLOCKS: dict = {}
REAL_NEW_SESSION = scripted.ScriptedProvider.new_session


def stealth_flow(admin: Api, base: dict):
    """«Medidas anti-bot»: el nivel se guarda, se exporta y su sesión se hace pasar por Chrome (o es Chrome)."""
    check(stealth.site_of("https://apiw.vueling.com/api/v1/x?a=1") == "https://www.vueling.com"
          and stealth.site_of("https://www.ryanair.com/api/x") == "https://www.ryanair.com"
          and stealth.site_of("https://wizzair.com/buildnumber") == "https://wizzair.com"
          and stealth.site_of("https://api.ejemplo.co.uk/x") == "https://www.ejemplo.co.uk"
          and stealth.site_of("http://127.0.0.1:8000/api") == "http://127.0.0.1:8000", "portada de la web de cada URL")
    # true/false (paquetes y clientes anteriores a los niveles) = huella de Chrome / ninguna.
    r = admin.post("/providers", {**base, "key": "sigilo", "label": "Sigilo", "stealth": True, "password": "clave-de-prueba-1"})
    prov = PROVIDERS["sigilo"]
    check(r.status_code == 201 and r.json()["provider"]["stealth"] == stealth.FINGERPRINT
          and prov.stealth == stealth.FINGERPRINT and prov.jitter >= 2,
          "proveedor con medidas anti-bot (y pausas más variables); true = huella de Chrome")
    pkg = bundle.loads(admin.get("/providers/export", params={"keys": "sigilo,miaero"}).text)
    check(sorted(p["stealth"] for p in pkg) == [0, 1], "el nivel viaja en el paquete exportado")
    r = admin.post("/providers", {**base, "key": "sigilo2", "stealth": 7, "password": "clave-de-prueba-1"})
    check(r.status_code == 422 and any("anti-bot" in e for e in r.json()["errors"]), "nivel de medidas anti-bot desconocido")
    r = admin.post("/providers", {**base, "key": "sigilo2", "stealth": 2, "password": "clave-de-prueba-1",
                                  "code": base["code"] + "\nBROWSER_PAGE = 'no es una url'\n"})
    check(r.status_code == 422 and "BROWSER_PAGE" in " ".join(r.json()["errors"]), "BROWSER_PAGE tiene que ser una URL")
    r, res, events = run_test(admin, {**base, "stealth": True, "password": "clave-de-prueba-1"})
    check("Medidas anti-bot: huella" in console_text(events), "la consola de la prueba dice qué medidas se aplican")
    r, res, events = run_test(admin, {**base, "stealth": 2, "password": "clave-de-prueba-1",
                                      "code": base["code"] + "\nBROWSER_PAGE = 'https://reservas.prueba.test/buscar'\n"})
    check("siempre Chrome" in console_text(events) and "https://reservas.prueba.test/buscar" in console_text(events),
          "la consola dice que todo va por Chrome y desde qué página")

    # La sesión: cliente con la huella de Chrome, visita previa a la portada y cabeceras de navegador…
    old_client, old_browser, old_pause = stealth.make_client, browser.BrowserFetch, stealth.WARMUP_PAUSE
    stealth.make_client, browser.BrowserFetch, stealth.WARMUP_PAUSE = FakeCurl, FakeBrowser, (0, 0)
    try:
        with REAL_NEW_SESSION(prov) as s:
            s.request("GET", "https://apiw.vueling.com/api/v1/availability", timeout=5, params={"o": "SVQ"})
            s.request("POST", "https://apiw.vueling.com/api/v1/otra", timeout=5, json={"a": 1}, headers={"X-Propia": "1"})
        calls = s.shared.client.calls
        check([(m, u) for m, u, _, _ in calls] == [("GET", "https://www.vueling.com/"),
                                                   ("GET", "https://apiw.vueling.com/api/v1/availability"),
                                                   ("POST", "https://apiw.vueling.com/api/v1/otra")]
              and calls[0][2]["Sec-Fetch-Mode"] == "navigate" and calls[1][2]["Origin"] == "https://www.vueling.com"
              and calls[1][2]["Referer"] == "https://www.vueling.com/" and calls[1][2]["Sec-Fetch-Site"] == "same-site"
              and calls[1][2]["Accept-Language"].startswith("es-ES") and calls[2][2]["X-Propia"] == "1"
              and calls[1][3] == {"params": {"o": "SVQ"}},
              "anti-bot: visita la portada una vez y llama a la API con las cabeceras de un navegador")
        with REAL_NEW_SESSION(prov) as s2:
            pass
        check(s2.shared is s.shared and len(s.shared.client.calls) == 3, "la sesión (y sus cookies) se reutiliza entre rondas")

        # …y si aun así choca con un anti-bot, repite desde Chrome y sigue con él.
        BLOCKS["https://apiw.vueling.com/api/v1/bloqueada"] = 403
        with REAL_NEW_SESSION(prov) as s3:
            r1 = s3.request("GET", "https://apiw.vueling.com/api/v1/bloqueada", timeout=5)
            r2 = s3.request("GET", "https://apiw.vueling.com/api/v1/availability", timeout=5)
        chrome = FakeBrowser.made[-1]
        check(r1.status_code == 200 and r1.json() == {"desde": "chrome"} and r2.json() == {"desde": "chrome"}
              and [u for _, _, u in chrome.calls] == ["https://apiw.vueling.com/api/v1/bloqueada",
                                                      "https://apiw.vueling.com/api/v1/availability"]
              and chrome.calls[0][0] == "https://www.vueling.com/" and chrome.closed and s3.shared.prefer_browser,
              "anti-bot: tras un bloqueo, lo repite desde Chrome (y lo cierra al acabar)")

        # «Siempre Chrome»: ni huella ni portada, todo por Chrome desde la página que pide el script.
        r = admin.post("/providers", {**base, "key": "chrome", "label": "Chrome", "stealth": 2, "password": "clave-de-prueba-1",
                                      "code": base["code"] + "\nBROWSER_PAGE = 'https://reservas.vueling.com/buscar'\n"})
        always = PROVIDERS["chrome"]
        check(r.status_code == 201 and r.json()["provider"]["stealth"] == stealth.BROWSER
              and always.browser_page == "https://reservas.vueling.com/buscar", "proveedor «Siempre Chrome» con su página")
        with REAL_NEW_SESSION(always) as s4:
            r1 = s4.request("GET", "https://apiw.vueling.com/api/v1/availability", timeout=5)
        chrome = FakeBrowser.made[-1]
        check(r1.json() == {"desde": "chrome"} and s4.shared.client.calls == [] and chrome.closed
              and chrome.calls == [("https://reservas.vueling.com/buscar", "GET", "https://apiw.vueling.com/api/v1/availability")],
              "siempre Chrome: va directo a Chrome, abierto en la BROWSER_PAGE del script")
        admin.delete("/providers/chrome")
    finally:
        stealth.make_client, browser.BrowserFetch, stealth.WARMUP_PAUSE = old_client, old_browser, old_pause
        BLOCKS.clear()
    admin.delete("/providers/sigilo")


def scripts_flow(admin: Api, admin_chan: int):
    scripted.ScriptedProvider.new_session = lambda self: FakeHttp()
    days = [(TODAY + timedelta(days=10 + i)).isoformat() for i in range(3)]
    HTTP.update({
        "https://api.prueba.test/rutas/SVQ": (200, {"destinos": ["TFN", "BCN"]}),
        "https://api.prueba.test/precios/SVQ/TFN": (200, {"dias": [
            {"fecha": days[0], "precio": 20}, {"fecha": days[1], "precio": 15, "moneda": "GBP"},
            {"fecha": days[2], "precio": 0}]}),
    })
    r = admin.get("/providers").json()
    check(r["editable"] and "def fetch_route" in r["template"] and len(r["catalogs"]) == len(bundle.CATALOGS), "lista de proveedores y plantilla")
    base = {"key": "miaero", "label": "Mi Aerolínea", "color": "#0EA5E9", "coverage": "network", "health_origin": "svq",
            "health_destination": "tfn", "min_interval": "0", "code": SCRIPT,
            "link_template": "https://www.miaero.test/vuelos?o={origin}&d={destination}&f={date}"}
    n_before = len(r["providers"])

    # --- validación y confirmación de la contraseña antes de ejecutar código
    bad = admin.post("/providers", {**base, "key": "Mal clave", "color": "rojo", "health_origin": "TCI",
                                    "link_template": "ftp://x", "code": ""})
    check(bad.status_code == 422 and all(t in errors(bad) for t in ("La clave", "hexadecimal", "aeropuerto", "https://", "Falta el código")),
          "validación del formulario del proveedor")
    check("Ya hay un proveedor" in errors(admin.post("/providers", {**base, "key": "vueling", "password": "clave-de-prueba-1"})),
          "la clave no puede repetirse (tampoco la de un incluido)")
    check("no puede ser «export»" in errors(admin.post("/providers", {**base, "key": "export"})), "claves reservadas por la API")
    r = admin.post("/providers", base)
    check(r.status_code == 403 and "Confirma tu contraseña" in errors(r), "guardar un script activo pide la contraseña")
    r = admin.post("/providers", {**base, "password": "mala"})
    check(r.status_code == 403 and "no es correcta" in errors(r), "contraseña incorrecta")
    r = admin.post("/providers", {**base, "password": "clave-de-prueba-1", "code": "def fetch_route(api,\n"})
    check(r.status_code == 422 and "Error de sintaxis en la línea" in errors(r), "error de sintaxis con su línea")
    r = admin.post("/providers", {**base, "password": "clave-de-prueba-1", "code": SCRIPT.replace("def network", "def red")})
    check(r.status_code == 422 and "Falta definir `network`" in errors(r), "el contrato exige la función de su cobertura")
    check(len(admin.get("/providers").json()["providers"]) == n_before, "nada se guarda si no carga")

    # --- probar sin guardar: consola en vivo con cada paso y cada petición, y el resultado al final
    r, res, events = run_test(admin, {**base, "password": "clave-de-prueba-1"})
    check(r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
          and res["status"] == "ok" and res["route"] == "SVQ→TFN"
          and [st["name"] for st in res["steps"]] == ["Carga del script", "Cobertura", "Precios (1 mes)"]
          and "2 destinos directos desde SVQ (incluye TFN)" in res["steps"][1]["detail"], "prueba del borrador: carga y cobertura")
    check(res["n_prices"] == 2 and res["sample"][1] == {"day": days[1], "price": 15, "currency": "GBP", "origin": "SVQ",
                                                        "destination": "TFN", "stops": 0}, "prueba del borrador: precios (sin los días a 0)")
    con_text = console_text(events)
    check("http: GET https://api.prueba.test/rutas/SVQ" in con_text and "ok:   ← 200 en" in con_text
          and "JSON: objeto con 1 clave: destinos" in con_text and "info: Llamo a network(api, 'SVQ')" in con_text
          and "http: GET https://api.prueba.test/precios/SVQ/TFN?meses=1" in con_text
          and "script: días recibidos: 3" in con_text and "step: Precios (1 mes)" in con_text
          and all(isinstance(e["t"], int) for e in events), "la consola cuenta cada paso, cada petición y los mensajes del script")
    with db.connect() as con:
        check("miaero" not in db.list_health(con), "la prueba de un borrador no se guarda como prueba de acceso")
    r, res, _ = run_test(admin, {**base, "password": "clave-de-prueba-1", "origin": "SVQ", "destination": "BCN",
                                 "code": SCRIPT.replace('data["dias"]]', 'data["días"]]')})
    check(res["steps"][2]["status"] == "empty", "una ruta sin precios en la prueba")
    HTTP["https://api.prueba.test/precios/SVQ/BCN"] = (200, {"dias": [{"fecha": days[0]}]})
    r, res, events = run_test(admin, {**base, "password": "clave-de-prueba-1", "origin": "SVQ", "destination": "BCN"})
    step = res["steps"][2]
    check(step["status"] == "error" and "KeyError: 'precio'" in step["detail"] and "línea 15 del script" in step["detail"],
          "un fallo del script dice qué falló y en qué línea")
    check("línea 15, en fetch_route: " in console_text(events) or "línea 15, en <listcomp>: " in console_text(events),
          "la consola muestra la línea del script que falla, con su código")
    HTTP["https://api.prueba.test/precios/SVQ/BCN"] = (429, {})
    r, res, events = run_test(admin, {**base, "password": "clave-de-prueba-1", "origin": "SVQ", "destination": "BCN"})
    check(res["status"] == "blocked" and "HTTP 429" in console_text(events), "un 429 de la web es «bloqueado»")
    r, res, events = run_test(admin, {**base, "password": "clave-de-prueba-1", "code": "print('hola')\nx = 1/0\ndef fetch_route(*a): pass"})
    check(res["steps"][0]["name"] == "Carga del script" and "ZeroDivisionError" in res["steps"][0]["detail"]
          and len(res["steps"]) == 1 and "script: hola" in console_text(events)
          and "línea 2, en <module>: x = 1/0" in console_text(events), "un script que falla al cargar (con su print y su línea)")
    check(admin.post("/providers/test", {**base, "password": "mala"}).status_code == 403, "probar también pide la contraseña")

    # --- tiempo límite de la prueba: por inactividad, no por duración (un proveedor lento que avanza no se corta)
    def draft(code, **limits):
        row = {"key": "lento", "label": "Lento", "color": "#000000", "coverage": "universal", "health_origin": "SVQ",
               "health_destination": "TFN", "min_interval": 0, "code": "import time\n" + code}
        lines = []
        res = health.check_draft(lambda say: scripted.ScriptedProvider(row, console=say), "SVQ", "TFN",
                                 lambda level, text: lines.append(text), **limits)
        return res, lines
    started = time.monotonic()
    res, _ = draft("def fetch_route(api, o, d, start, months):\n"
                   "    for _ in range(5):\n        time.sleep(0.2)\n        api.get_json(f'https://api.prueba.test/precios/{o}/{d}')\n"
                   "    return {}\n", idle_timeout=0.5, max_time=10)
    check(res["status"] == "empty" and time.monotonic() - started > 0.9,
          "una prueba que tarda más que el límite de inactividad pero sigue haciendo peticiones no se corta")
    res, lines = draft("def fetch_route(api, o, d, start, months):\n    time.sleep(1)\n    try:\n"
                       "        api.get_json('https://api.prueba.test/rutas/SVQ')\n    except Exception as exc:\n"
                       "        api.log('después:', exc)\n    return {}\n", idle_timeout=0.3, max_time=10)
    steps = res["steps"]
    check(res["status"] == "timeout" and [s["name"] for s in steps] == ["Carga del script", "Cobertura", "Precios (1 mes)"]
          and steps[0]["status"] == "ok" and "Sin respuesta ni actividad" in steps[-1]["detail"],
          "un script colgado se corta por inactividad, conservando los pasos terminados")
    time.sleep(1)
    check(any("prueba cortada" in t for t in lines), "tras cortarla, el script ya no puede hacer peticiones")
    res, _ = draft("def fetch_route(api, o, d, start, months):\n    for _ in range(20):\n        time.sleep(0.1)\n"
                   "        api.log('sigo')\n    return {}\n", idle_timeout=0.5, max_time=0.6)
    check(res["status"] == "timeout" and "tope de la prueba" in res["steps"][-1]["detail"],
          "aunque siga avanzando, la prueba tiene un tope total")

    # --- una petición sin respuesta a tiempo se repite una vez; el script puede esperar más a una web lenta
    lenta = "def fetch_route(api, o, d, start, months):\n    api.post_json('https://api.prueba.test/lenta', {}, timeout=45)\n    return {}\n"
    HTTP["https://api.prueba.test/lenta"] = ["timeout", (200, {"ok": 1})]
    WAITS.clear()
    res, lines = draft(lenta)
    check(res["status"] == "empty" and WAITS == [45, 45] and any("lo repito una vez" in t for t in lines),
          "sin respuesta a tiempo: se repite una vez (con el timeout que pide el script)")
    HTTP["https://api.prueba.test/lenta"] = ["timeout"]
    res, lines = draft(lenta.replace(", timeout=45", ""))
    check(res["status"] == "timeout" and res["steps"][-1]["status"] == "timeout"
          and "no ha respondido en 30 s" in res["steps"][-1]["detail"],
          "si tampoco responde la segunda vez, el paso sale como «sin respuesta» con el tiempo que esperó")

    # --- guardado: entra en el registro y lo usan vigilancias, ronda, avisos y enlaces
    r = admin.post("/providers", {**base, "password": "clave-de-prueba-1"})
    s = r.json()["provider"]
    check(r.status_code == 201 and s["loaded"] and s["updated_by"] == "admin" and s["color"] == "#0ea5e9"
          and s["health_origin"] == "SVQ" and s["source"] is None and "miaero" in PROVIDERS, "crear proveedor")
    check("miaero" in {p["key"] for p in admin.get("/meta").json()["providers"]}
          and "miaero" in {p["key"] for p in admin.get("/providers").json()["providers"]},
          "aparece en el panel y en la zona Proveedores")
    r = admin.post("/watches", {"name": "Script", "origin": "SVQ", "destination": "TFN", "providers": ["miaero"],
                                "max_price": "30", "channel_ids": [admin_chan]})
    w = r.json()["watch"]
    check(r.status_code == 201 and w["coverage"][0]["routes"] == ["SVQ-TFN"], "vigilancia con el proveedor (cobertura del script)")
    SENT.clear()
    checker.run_checks(watch_id=w["id"], trigger="manual")
    with db.connect() as con:
        snap = db.latest_snapshot(con, w["id"], "miaero")
    check(len(snap) == 2 and snap[0]["currency"] == "GBP" and snap[0]["orig_price"] == 15 and round(snap[0]["price"], 2) == 17.65,
          "la ronda guarda sus precios (en euros y en la moneda original)")
    msg = "\n".join(SENT[0][0]) if SENT else ""
    check("**Mi Aerolínea**" in msg and f"https://www.miaero.test/vuelos?o=SVQ&d=TFN&f={days[1]}" in msg,
          "el aviso lleva su nombre y su plantilla de enlace")
    check({p["key"]: p for p in admin.get("/providers").json()["providers"]}["miaero"]["n_watches"] == 1, "cuántas vigilancias lo usan")

    # --- cambios: la contraseña solo se pide si se va a ejecutar código nuevo
    r = admin.put("/providers/miaero", {**base, "label": "Mi Aerolínea 2"})
    check(r.status_code == 200 and PROVIDERS["miaero"].label == "Mi Aerolínea 2", "cambiar el nombre no pide contraseña")
    r = admin.put("/providers/miaero", {**base, "code": SCRIPT + "\n# cambio\n"})
    check(r.status_code == 403, "cambiar el código pide la contraseña")
    with db.connect() as con:
        cached = len(db.cached_routes(con, "miaero", [("SVQ", "TFN")], "2000-01-01"))
    r = admin.put("/providers/miaero", {**base, "code": SCRIPT + "\n# cambio\n", "password": "clave-de-prueba-1"})
    with db.connect() as con:
        check(r.status_code == 200 and cached == 1 and not db.cached_routes(con, "miaero", [("SVQ", "TFN")], "2000-01-01"),
              "al cambiar el código se olvida la cobertura que dio el script anterior")
    r = admin.put("/providers/miaero", {**base, "enabled": False})
    check(r.status_code == 200 and "miaero" not in PROVIDERS and not r.json()["provider"]["loaded"],
          "desactivarlo lo saca del registro sin pedir contraseña")
    check(admin.get(f"/watches/{w['id']}").status_code == 200, "la vigilancia sigue funcionando sin él")
    r = admin.put(f"/watches/{w['id']}", {"name": "Script", "origin": "SVQ", "destination": "TFN", "providers": ["google"],
                                          "max_price": "30", "channel_ids": [admin_chan]})
    with db.connect() as con:
        kept = db.get_watch(con, w["id"])["coverage"]
    check(r.status_code == 200 and set(kept) == {"google", "miaero"} and kept["miaero"]["routes"] == [("SVQ", "TFN")],
          "editar la vigilancia mientras está desactivado no se lo quita")
    check(admin.put("/providers/miaero", base).status_code == 403, "reactivarlo pide la contraseña")
    r = admin.put("/providers/miaero", {**base, "password": "clave-de-prueba-1"})
    check(r.status_code == 200 and "miaero" in PROVIDERS, "reactivado")

    # --- un script guardado que deja de cargar no tumba el servidor
    with db.connect() as con:
        db.save_provider_script(con, "roto", {**{k: v for k, v in base.items() if k != "key"}, "health_origin": "SVQ",
                                              "health_destination": "TFN", "max_routes": None, "notes": "", "min_interval": 0,
                                              "enabled": 1, "code": "import modulo_que_no_existe\n"}, "admin")
    scripted.reload()
    roto = {x["key"]: x for x in admin.get("/providers").json()["providers"]}["roto"]
    check(not roto["loaded"] and "ModuleNotFoundError" in roto["error"] and "roto" not in PROVIDERS and "miaero" in PROVIDERS,
          "un script que no carga se marca con su error y los demás siguen")
    check(admin.delete("/providers/roto").status_code == 204, "eliminar el script roto")

    r = admin.post("/providers", {**base, "key": "universal", "label": "Universal", "coverage": "universal",
                                  "max_routes": "4", "password": "clave-de-prueba-1"})
    check(r.status_code == 201 and PROVIDERS["universal"].max_routes == 4, "proveedor de cobertura universal")
    admin.delete("/providers/universal")
    stealth_flow(admin, base)

    # --- PROVIDER_SCRIPTS=0: se siguen ejecutando, pero no se puede cambiar código desde el panel
    scripted.EDITABLE = False
    check(run_test(admin, {**base, "password": "clave-de-prueba-1"})[0].status_code == 403
          and admin.put("/providers/miaero", {**base, "code": SCRIPT + "#x\n", "password": "clave-de-prueba-1"}).status_code == 403
          and admin.post("/providers/import", {"text": "x", "keys": ["x"]}).status_code == 403
          and not admin.get("/providers").json()["editable"],
          "PROVIDER_SCRIPTS=0: no se puede probar, cambiar el código ni importar")
    check(admin.put("/providers/miaero", {**base, "label": "Mi Aerolínea"}).status_code == 200
          and admin.get("/providers/export").status_code == 200, "…pero sí renombrar o exportar")
    scripted.reload()
    check("miaero" in PROVIDERS and "vueling" in PROVIDERS, "PROVIDER_SCRIPTS=0: los proveedores siguen cargados")
    scripted.EDITABLE = True

    # --- eliminar: se quita de las vigilancias, el histórico se conserva
    check(admin.delete("/providers/miaero").status_code == 204 and "miaero" not in PROVIDERS, "eliminar proveedor")
    detail = admin.get(f"/watches/{w['id']}")
    check(detail.status_code == 200 and detail.json()["watch"]["providers"] == ["google"], "la vigilancia ya no lo tiene")
    with db.connect() as con:
        kept = con.execute(text("SELECT count(*) FROM prices WHERE provider = 'miaero'")).scalar()
    check(kept == 2 and admin.get(f"/watches/{w['id']}/charts").status_code == 200, "sus precios se conservan como histórico")
    check(admin.get("/providers/miaero").status_code == 404, "ya no existe")
    admin.delete(f"/watches/{w['id']}")


def bundle_flow(admin: Api):
    """Proveedores incluidos (creados al arrancar), el catálogo y paquetes: exportar, vista previa e importar."""
    lst = admin.get("/providers").json()["providers"]
    check([p["key"] for p in lst] == ["ryanair", "vueling"] and all(p["loaded"] and p["enabled"] for p in lst)
          and lst[0]["updated_by"] == "flight-watcher" and lst[0]["source"] == bundle.CATALOG_URL + "providers.fwp"
          and "wizzair" not in PROVIDERS, "al arrancar se crean Vueling y Ryanair como scripts (y nada más)")
    with db.connect() as con:
        check(db.get_setting(con, bundle.SEED_FLAG) == "1" and bundle.seed() == [], "la siembra ocurre una sola vez")
        db.replace_provider_source(con, bundle.CATALOG_URL + "providers.fwp", bundle.CATALOG_URL + "incluidos.fwp")
        before = db.get_provider_script(con, "vueling")["updated_at"]
    bundle.seed()
    with db.connect() as con:
        row = db.get_provider_script(con, "vueling")
    check(row["source"] == bundle.CATALOG_URL + "providers.fwp" and row["updated_at"] == before,
          "al arrancar, el enlace guardado de un paquete antiguo del catálogo pasa al catálogo (sin contar como cambio)")

    # --- exportar: todos o los elegidos, con el código tal cual
    r = admin.get("/providers/export")
    pkg = bundle.loads(r.text)
    with db.connect() as con:
        code = db.get_provider_script(con, "vueling")["code"]
    check(r.status_code == 200 and "attachment" in r.headers["content-disposition"] and r.text.startswith("#flight-watcher:proveedores v1")
          and [p["key"] for p in pkg] == ["ryanair", "vueling"] and pkg[1]["code"] == code and "def probe(api, origin, destination):" in r.text,
          "exportar todos (el script se lee tal cual en el archivo)")
    r = admin.get("/providers/export", params={"keys": "ryanair"})
    check([p["key"] for p in bundle.loads(r.text)] == ["ryanair"] and "proveedores-ryanair.fwp" in r.headers["content-disposition"],
          "exportar los elegidos")
    check(admin.get("/providers/export", params={"keys": "nope"}).status_code == 404, "exportar uno que no existe")

    # --- el formato: el separador nunca choca con el código y los errores se explican
    tricky = {"key": "raro", "label": "Raro", "code": 'x = """\n%%fw%% no es un separador\n"""\n', "min_interval": 1}
    text_ = bundle.dumps([tricky])
    check(text_.splitlines()[0].endswith("separador=%%fw2%%") and bundle.loads(text_)[0]["code"] == tricky["code"],
          "si una línea del código empieza por el separador, se elige otro")
    for bad, msg in (("hola", "primera línea"), ("<!doctype html><html>", "archivo en bruto"),
                     ("#flight-watcher:proveedores v9 separador=%%", "versión del formato"),
                     ("#flight-watcher:proveedores v1 separador=%%\nx = 1", "solo puede haber comentarios"),
                     ("#flight-watcher:proveedores v1 separador=%%\n%% {mal", "no son JSON"),
                     ('#flight-watcher:proveedores v1 separador=%%\n%% {"key": "a"}\n%% {"key": "a"}', "repite la clave"),
                     ("#flight-watcher:proveedores v1 separador=%%\n# nada", "ningún proveedor")):
        try:
            bundle.loads(bad)
            check(False, f"paquete no válido: {msg}")
        except bundle.BundleError as exc:
            check(msg in str(exc), f"paquete no válido: {msg}")

    # --- el catálogo: un solo paquete con todos; se lee, sus scripts cargan y el panel ofrece su enlace de GitHub
    loaded = []
    for p in bundle.loads(bundle.CATALOG.read_text("utf-8")):
        scripted.load(p["key"], p["code"], p["coverage"])
        loaded.append(p["key"])
    offered = [c["url"] for c in admin.get("/providers").json()["catalogs"]]
    check(loaded == ["vueling", "ryanair", "wizzair", "google", "aireuropa"]
          and offered == [bundle.CATALOG_URL + "providers.fwp"] and sorted(p.name for p in bundle.CATALOG_DIR.glob("*.fwp")) == ["providers.fwp"],
          "catálogo: providers.fwp tiene todos los proveedores, sus scripts cargan y el panel lo ofrece")
    check(bundle.raw_url("https://github.com/katarem/flight-watcher/blob/main/app/providers/catalog/sin-verificar.fwp")
          == bundle.raw_url(bundle.CATALOG_URL + "incluidos.fwp") == bundle.CATALOG_URL + "providers.fwp",
          "los enlaces de los paquetes antiguos del catálogo llevan a providers.fwp")

    # --- vista previa desde un enlace (el de GitHub se cambia por el del archivo en bruto) y desde un archivo
    url = "https://github.com/katarem/flight-watcher/blob/main/app/providers/catalog/providers.fwp"
    r = admin.post("/providers/import/preview", {"url": url})
    prev = r.json()
    check(r.status_code == 200 and prev["source"] == bundle.CATALOG_URL + "providers.fwp"
          and [(p["key"], p["status"], p["errors"]) for p in prev["providers"]]
          == [("vueling", "same", []), ("ryanair", "same", []), ("wizzair", "new", []), ("google", "new", []), ("aireuropa", "new", [])]
          and "def fetch_route" in prev["providers"][3]["code"], "vista previa de un enlace: qué trae y qué haría")
    bad = admin.post("/providers/import/preview", {"url": "https://ejemplo.test/nada.fwp"})
    check(bad.status_code == 422 and "no existe" in errors(bad), "un enlace que no existe")
    check("Indica un enlace" in errors(admin.post("/providers/import/preview", {})), "sin enlace ni archivo")
    mine = admin.get("/providers/export").text.replace('"label": "Ryanair"', '"label": "Ryanair (copia)"')
    r = admin.post("/providers/import/preview", {"text": mine})
    status = {p["key"]: (p["status"], p["changes"]) for p in r.json()["providers"]}
    check(r.json()["source"] is None and status == {"vueling": ("same", []), "ryanair": ("changed", ["label"])},
          "vista previa de un archivo: igual o con cambios respecto a los guardados")
    broken = bundle.dumps([{"key": "Mala clave", "label": "", "color": "x", "coverage": "network", "code": "def fetch_route(): pass"}])
    p = admin.post("/providers/import/preview", {"text": broken}).json()["providers"][0]
    check(p["status"] == "new" and any("La clave" in e for e in p["errors"]) and any("hexadecimal" in e for e in p["errors"]),
          "la vista previa avisa de lo que no se podría importar")

    # --- importar: pide la contraseña, todo o nada, y guarda de dónde vino
    body = {"text": prev["text"], "url": prev["source"], "keys": ["wizzair", "google"]}
    r = admin.post("/providers/import", body)
    check(r.status_code == 403 and "Confirma tu contraseña" in errors(r), "importar pide la contraseña")
    check("Elige al menos un proveedor" in errors(admin.post("/providers/import", {**body, "keys": []})), "hay que elegir alguno")
    bad_code = bundle.dumps([{"key": "falla", "label": "Falla", "color": "#000000", "coverage": "network",
                              "health_origin": "SVQ", "health_destination": "TFN", "code": "def fetch_route(*a): pass\n"}])
    r = admin.post("/providers/import", {"text": bad_code, "keys": ["falla"], "password": "clave-de-prueba-1"})
    check(r.status_code == 422 and "Falta definir `network`" in errors(r) and "falla" not in PROVIDERS,
          "un script que no carga no se importa (y no se importa nada)")
    r = admin.post("/providers/import", {**body, "password": "clave-de-prueba-1"})
    lst = {p["key"]: p for p in admin.get("/providers").json()["providers"]}
    check(r.status_code == 200 and r.json()["imported"] == r.json()["created"] == ["wizzair", "google"]
          and PROVIDERS["google"].stops_filter and PROVIDERS["google"].max_routes == 12
          and lst["wizzair"]["source"] == bundle.CATALOG_URL + "providers.fwp" and lst["wizzair"]["updated_by"] == "admin"
          and "aireuropa" not in lst, "importar desde un enlace solo los elegidos (Wizz Air y Google Flights quedan activos)")
    check(admin.get("/providers").json()["sources"] == [bundle.CATALOG_URL + "providers.fwp"],
          "los enlaces ya usados se recuerdan para volver a importar")
    r = admin.post("/providers/import", {"text": mine, "keys": ["ryanair"], "enabled": True, "password": "clave-de-prueba-1"})
    check(r.status_code == 200 and r.json()["created"] == [] and PROVIDERS["ryanair"].label == "Ryanair (copia)",
          "importar sustituye a uno con la misma clave")
    admin.post("/providers/import", {"url": bundle.CATALOG_URL + "incluidos.fwp", "keys": ["ryanair"], "password": "clave-de-prueba-1"})
    check(PROVIDERS["ryanair"].label == "Ryanair", "volver a importar el original (con el enlace antiguo del catálogo)")


def main():
    with TestClient(app) as raw:
        client = Api(raw)

        # --- el panel compilado se sirve desde WEB_DIR y el enrutado lo resuelve el navegador
        r = raw.get("/")
        check(r.status_code == 200 and 'id="root"' in r.text and r.headers["cache-control"] == "no-cache", "GET / entrega el panel")
        check('id="root"' in raw.get("/watches/12").text and 'id="root"' in raw.get("/admin/users").text,
              "cualquier ruta del panel entrega index.html (enrutado del lado cliente)")
        r = raw.get("/assets/app-1234.js")
        check(r.status_code == 200 and "immutable" in r.headers["cache-control"], "estáticos con huella y caché larga")
        check(raw.get("/favicon.svg").text == "<svg/>", "archivos sueltos del build")
        check(raw.get("/assets/viejo-0000.js").status_code == 404, "un estático que ya no existe es 404, no el panel")
        r = raw.get("/..%2F..%2Fetc%2Fpasswd")
        check("root:" not in r.text and 'id="root"' in r.text, "el panel no sirve archivos fuera de su carpeta")
        r = raw.get("/api/v1/no-existe")
        check(r.status_code == 404 and r.headers["content-type"].startswith("application/json"), "una ruta de API desconocida es 404 JSON")

        # --- sesión: sin login no hay acceso
        check(client.get("/me").status_code == 401 and client.get("/watches").status_code == 401, "la API responde 401 sin sesión")
        check(client.get("/openapi.json").status_code == 401 and client.get("/docs").status_code == 401, "la documentación de la API exige sesión")
        check(raw.post("/api/v1/session", json={"username": "admin", "password": "clave-de-prueba-1"}).status_code == 403,
              "sin la cabecera anti-CSRF no se acepta ningún cambio")
        r = client.login("admin", "mala")
        check(r.status_code == 401 and "incorrectos" in errors(r), "contraseña incorrecta rechazada")
        check(client.login("nadie", "x").status_code == 401, "usuario inexistente rechazado")
        for _ in range(5):
            client.login("bloqueado", "x")
        r = client.login("bloqueado", "x")
        check(r.status_code == 429 and "Demasiados intentos" in errors(r), "freno tras varios intentos fallidos")
        r = client.login("Admin", "clave-de-prueba-1")
        check(r.status_code == 200 and r.json()["user"]["role"] == "admin", "login válido (usuario sin distinguir mayúsculas)")
        with db.connect() as con:
            admin_id = db.get_user_by_username(con, "admin")["id"]
            admin_row = db.get_user(con, admin_id)
        check(admin_row["password_hash"].startswith("scrypt$"), "administrador inicial con hash scrypt")
        check(client.get("/docs").status_code == 200 and "/api/v1/watches" in client.get("/openapi.json").json()["paths"],
              "documentación de la API con sesión")
        check(raw.get("/index.html").headers["cache-control"] == "no-cache", "index.html nunca se queda en caché")
        meta = client.get("/meta").json()
        check(meta["version"] and {p["key"] for p in meta["providers"]} >= {"vueling", "ryanair"}, "metadatos del panel")
        bundle_flow(client)

        # --- lecturas base
        for path in ("/watches", "/alerts", "/runs", "/settings", "/debug/files", "/users", "/channels", "/status"):
            check(client.get(path).status_code == 200, f"GET {path}")
        cards = client.get("/watches").json()["watches"]
        check([(w["name"], w["origin"], w["destination"]) for w in cards]
              == [("Sevilla → Tenerife", "SVQ", "TCI"), ("Tenerife → Sevilla", "TCI", "SVQ")],
              "vigilancias iniciales sembradas (SVQ ↔ TCI)")

        # --- ronda 1 (sin histórico): solo aplica el precio máximo
        with db.connect() as con:
            admin_chan = db.create_channel(con, admin_id, "discord", "Discord admin", {"webhook": "https://discord.com/api/webhooks/1/admin"})
            for w in db.list_watches(con, admin_id):
                db.set_watch_channels(con, w["id"], [admin_chan])
        check(checker.run_checks(trigger="manual") == "done", "run_checks termina")
        check(len(SENT) == 2 and set(TARGETS) == {("Discord admin",)},
              f"un aviso por vigilancia, a sus canales asignados ({len(SENT)})")
        discord = "\n".join(SENT[0][0])
        telegram = "\n".join(SENT[0][1])
        target_day = (TODAY + timedelta(days=11)).isoformat()
        check(f"dd={target_day}" in discord and "o=SVQ&d=TFN" in discord, "enlace Vueling con la fecha elegida")
        check("<a href=" in telegram and "&amp;dd=" in telegram, "enlace en HTML escapado para Telegram")
        check("30 €" in discord, "precio bajo incluido en el aviso")
        check("Ryanair" not in discord, "Ryanair (45 €) no supera el precio máximo de 40 €")
        with db.connect() as con:
            routes_saved = {(r[0], r[1], r[2]) for r in con.execute(text("SELECT provider, origin, destination FROM prices"))}
        check(("vueling", "SVQ", "TFN") in routes_saved and ("ryanair", "SVQ", "TFS") in routes_saved
              and not any(o == "TCI" or d == "TCI" for _, o, d in routes_saved),
              "TCI se expande a TFN/TFS y se guarda el aeropuerto real")
        runs = client.get("/runs").json()["runs"]
        check(all(r["ok"] for r in runs) and not any("La web no devolvió" in (r["error"] or "") for r in runs),
              "una ruta no operada dentro de TCI no cuenta como error")

        # --- no repite avisos de lo ya notificado
        SENT.clear()
        checker.run_checks(trigger="manual")
        check(not SENT, "no reenvía avisos ya enviados")

        # --- regla relativa: histórico caro previo + precio actual muy inferior
        with db.connect() as con:
            wid = db.create_watch(con, admin_id, {
                "name": "Prueba relativa", "origin": "MAD", "destination": "BCN", "providers": ["mockweb"],
                "max_price": None, "discount_pct": 30, "date_from": None, "date_to": None, "enabled": True,
            })
            db.set_watch_channels(con, wid, [admin_chan])
            old = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
            db.insert_prices(con, wid, "mockweb", old, [DayPrice(TODAY + timedelta(days=20 + i), 200) for i in range(40)])
        SENT.clear()
        checker.run_checks(watch_id=wid, trigger="manual")
        check(len(SENT) == 1 and "habitual ≈ 200 €" in "\n".join(SENT[0][0]), "regla relativa sobre la mediana histórica")

        # --- detalle, calendario y gráficas
        detail = client.get(f"/watches/{wid}").json()
        day = (TODAY + timedelta(days=11)).isoformat()  # el más barato de la ronda simulada
        check(detail["prices"][0]["flight_date"] == day and detail["prices"][0]["price"] == 95, "precios de la última comprobación (del más barato)")
        st = detail["stats"][0]
        check(st["best"]["deal"] == "relative" and st["base"] == 200 and st["count"] == 3 and st["median"] == 120,
              "resumen por web: chollo, habitual, mediana y nº de fechas")
        check(detail["checks"] and 95 in [a["price"] for a in detail["alerts"]], "historial de comprobaciones y avisos")
        charts = client.get(f"/watches/{wid}/charts").json()
        check(charts["min_over_time"]["labels"] and "mockweb" in charts["min_over_time"]["series"], "API de gráficas")
        hist = client.get(f"/watches/{wid}/date-history", params={"date": (TODAY + timedelta(days=20)).isoformat()}).json()
        check(len(hist["labels"]) >= 1, "API del historial de una fecha")
        cards = {w["id"]: w for w in client.get("/watches").json()["watches"]}
        stats = {s["key"]: s for s in cards[1]["stats"]}
        check("tickets.vueling.com/booking" in stats["vueling"]["best"]["link"] and "d=TFN" in stats["vueling"]["best"]["link"],
              "el panel muestra el enlace con fecha y aeropuerto real")
        check("originIata=SVQ&destinationIata=TFS" in stats["ryanair"]["best"]["link"] and stats["ryanair"]["best"]["route"] == "SVQ→TFS",
              "Ryanair enlaza a TFS dentro de TCI")
        check(len(cards[wid]["trend"]) == 2 and cards[wid]["trend"][-1]["p"] == 95, "tendencia del precio mínimo para la minigráfica")
        check(client.get("/alerts?limit=3").json()["alerts"][0]["watch_name"], "últimos avisos del usuario")

        # --- ajustes y sus validaciones (las plantillas de enlace ya no están aquí: son de cada proveedor)
        r = client.put("/settings", {
            "schedule_hours": "8,20", "schedule_minute": "30", "timezone": "Europe/Madrid", "max_months": "11",
            "min_samples": "30", "retention_days": "400", "headless": "1", "debug": False,
            "link_ryanair": "https://www.ryanair.com/x?o={origin}&d={destination}&f={date_dmy}",
        })
        check(r.status_code == 200 and r.json()["values"]["schedule_hours"] == "8,20"
              and not any(k.startswith("link_") for k in r.json()["values"]), "guardar ajustes")
        s = db.get_settings()
        check(s["schedule_hours"] == "8,20" and s["debug"] == "0", "ajustes persistidos")
        with db.connect() as con:
            check(len(db.list_channels(con, admin_id)) == 1, "los ajustes no tocan los canales del usuario")
        bad = client.put("/settings", {"schedule_hours": "99", "schedule_minute": "0", "timezone": "Nope/Zone",
                                       "max_months": "11", "min_samples": "30", "retention_days": "400"})
        check(bad.status_code == 422 and "Las horas deben ser" in errors(bad) and "Zona horaria desconocida" in errors(bad), "validación de ajustes")
        check("link_ryanair" not in s, "una plantilla de enlace en Ajustes ya no se guarda")
        ryan = client.get("/providers/ryanair").json()["provider"]
        original = ryan["link_template"]
        r = client.put("/providers/ryanair", {**ryan, "link_template": "https://www.ryanair.com/x?o={origin}&d={destination}&f={date_dmy}"})
        check(r.status_code == 200 and link_for("ryanair", "SVQ", "TFN", date(2026, 10, 24)).endswith("f=24/10/2026"),
              "plantilla de enlace del proveedor (cambiarla no pide contraseña)")
        client.put("/providers/ryanair", {**ryan, "link_template": original})

        # --- CRUD de vigilancias
        bad = client.post("/watches", {"origin": "S1", "destination": "TFN"})
        check(bad.status_code == 422 and "código IATA" in errors(bad) and "al menos un proveedor" in errors(bad), "validación del formulario")
        bad = client.post("/watches", {"origin": 3, "providers": "x"})
        check(bad.status_code == 422 and "Datos no válidos" in errors(bad), "tipos incorrectos → 422 en castellano")
        bad = client.post("/watches", {"origin": "agp", "destination": "bcn", "providers": ["vueling"]})
        check(bad.status_code == 422 and "Vueling no opera esta ruta" in errors(bad), "un proveedor que no opera la ruta no se puede elegir")
        r = client.post("/watches", {"origin": "agp", "destination": "bcn", "providers": ["mockweb", "nope"], "max_price": "25,5"})
        check(r.status_code == 201, "crear vigilancia")
        new = r.json()["watch"]
        check(new["origin"] == "AGP" and new["destination"] == "BCN" and new["max_price"] == 25.5 and new["providers"] == ["mockweb"]
              and new["name"] == "AGP → BCN", "IATA en mayúsculas, decimales con coma y proveedores desconocidos fuera")
        r = client.post(f"/watches/{new['id']}/toggle")
        check(r.status_code == 200 and r.json()["watch"]["enabled"] is False, "pausar/reanudar")
        check(client.delete(f"/watches/{new['id']}").status_code == 204 and client.get(f"/watches/{new['id']}").status_code == 404, "eliminar")
        st = client.get("/status").json()
        check(st["running"] is False and st["current"] == "" and st["next_run"], "estado de ejecución y próxima ronda")
        check(sum(1 for r in client.get("/runs").json()["runs"] if r["ok"]) >= 2, "historial de ejecuciones")

        tid = trips_flow(client, admin_chan)
        providers_flow(client, admin_id, admin_chan)
        scripts_flow(client, admin_chan)
        users_flow(client, admin_id)
        with db.connect() as con:
            check(db.get_trip(con, tid) is not None, "el viaje sigue ahí tras las demás pruebas")

    # --- extractor genérico
    out = {}
    walk_json({"data": {"calendar": [{"departureDate": "2026-10-24T06:00:00", "price": {"amount": 34.5, "currency": "EUR"}, "taxAmount": 9},
                                     {"date": "2026-10-25", "lowestPrice": 41}]}, "map": {"2026-11-02": 29, "2026-11-03": {"price": 33}}}, out)
    check(out[date(2026, 10, 24)] == 34.5 and out[date(2026, 10, 25)] == 41 and out[date(2026, 11, 2)] == 29
          and out[date(2026, 11, 3)] == 33, "walk_json: registros, precios anidados y mapas por fecha")
    check(parse_day("sábado, 24 de octubre de 2026") == date(2026, 10, 24) and parse_day("2026-10-24") == date(2026, 10, 24), "parse_day")
    check(parse_price("desde 45,50 €") == 45.5 and parse_price("24 45€") == 45.0 and parse_price("sin precio") is None, "parse_price")

    # --- la base de datos está consistente
    if config.DB_ENGINE == "sqlite":
        con = sqlite3.connect(config.DB_PATH)
        check(con.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "integridad SQLite")
    print("\nTodo correcto.")


if __name__ == "__main__":
    main()
