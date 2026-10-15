"""Test de humo sin red ni navegador real: `python -m tests.smoke_test`

Sustituye el navegador y los proveedores por datos simulados y comprueba de extremo a extremo:
guardado de precios, reglas de aviso, enlaces con fecha, mensajes, la API del panel (sesión, permisos,
vigilancias, gráficas, canales, usuarios, ajustes), lugares y cobertura de rutas, escalas y monedas, la
revalidación semanal, los proveedores (incluidos, scripts, prueba con consola, exportar e importar paquetes y
prueba de acceso), los viajes de ida y vuelta, el alojamiento y los viajeros (2.1) y que el servidor entrega el panel
compilado.
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

from app import checker, config, coverage, db, fx, health, images, notify, party, places, stays, trips  # noqa: E402
from app.main import app  # noqa: E402
from app.providers import PROVIDERS, DayPrice, link_for  # noqa: E402
from app.providers.base import Provider  # noqa: E402
from app.providers.extract import parse_day, parse_price, walk_json  # noqa: E402
from app.providers import browser, bundle, scripted, stealth  # noqa: E402

from . import fakes  # noqa: E402
from .fakes import ASKED, SENT, TARGETS, TODAY  # noqa: E402

fakes.install()

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==")
CSRF = {"X-Requested-With": "trip-watch"}


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


def leg(origin, destination, providers, kind="flight", max_stops=0, name=""):
    """Datos de un tramo para el cuerpo de `POST/PUT /trips`."""
    return {"origin": origin, "destination": destination, "providers": providers, "kind": kind,
            "max_stops": max_stops, "name": name}


def oneway(api, providers, origin="MAD", destination="BCN", *, kind="flight", max_stops=0, name="",
           max_total=None, channel_ids=None):
    """Crea un viaje de solo ida (un único tramo) y devuelve la respuesta cruda de `POST /trips`.

    Sustituye a las vigilancias sueltas: para probar algo a nivel de tramo (proveedor, cobertura, detalle), se
    crea un viaje de solo ida y se usa su tramo de ida (`trip["outbound"]`)."""
    body = {"name": name, "min_nights": 1, "max_nights": 1, "max_total": max_total,
            "outbound": leg(origin, destination, providers, kind, max_stops)}
    if channel_ids is not None:
        body["channel_ids"] = channel_ids
    return api.post("/trips", body)


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
    check(not ana_c.get("/trips").json()["trips"], "no ve viajes ajenos")
    me = ana_c.get("/me").json()["user"]
    check(me["display_name"] == "Ana García" and me["role"] == "user" and "password_hash" not in me, "/me con sus datos")
    for path in ("/watches/1", "/watches/1/charts", "/watches/1/date-history?date=2026-01-01"):
        check(ana_c.get(path).status_code == 404, f"{path} (tramo de otro usuario) → 404")
    seeded_trip = admin.get("/trips").json()["trips"][0]["id"]
    for method, path in (("GET", f"/trips/{seeded_trip}"), ("PUT", f"/trips/{seeded_trip}"),
                         ("DELETE", f"/trips/{seeded_trip}"), ("POST", f"/trips/{seeded_trip}/toggle"),
                         ("POST", f"/trips/{seeded_trip}/run")):
        check(ana_c.req(method, path, json={} if method == "PUT" else None).status_code == 404, f"{method} {path} ajeno → 404")
    check(admin.get("/watches/1").status_code == 200, "el dueño sigue accediendo a su tramo")
    check(ana_c.get("/status").json()["current"] == "", "estado de ejecución sin nombres ajenos")

    r = oneway(ana_c, ["mockweb"], max_total=100, name="Viaje de Ana")
    check(r.status_code == 201, "Ana crea su viaje")
    ana_trip = r.json()["trip"]
    ana_watch = ana_trip["outbound"]
    with db.connect() as con:
        check(db.get_watch(con, ana_watch["id"])["user_id"] == ana_id, "el tramo pertenece a Ana")
    names = lambda c: [t["name"] for t in c.get("/trips").json()["trips"]]  # noqa: E731
    check("Viaje de Ana" in names(ana_c) and "Viaje de Ana" not in names(admin), "cada uno ve solo los suyos")
    check(admin.get(f"/trips/{ana_trip['id']}").status_code == 404, "ni el admin ve el de Ana")

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

    # --- asignar canales a cada viaje
    ids = {n: c["id"] for n, c in chans.items()}
    with db.connect() as con:
        admin_chan_id = db.list_channels(con, admin_id)[0]["id"]
    form = {"name": "Viaje de Ana", "outbound": leg("MAD", "BCN", ["mockweb"]), "min_nights": 1, "max_nights": 1,
            "max_total": "100"}
    r = ana_c.put(f"/trips/{ana_trip['id']}", {**form, "channel_ids": [ids["Mi Discord"], admin_chan_id]})
    check(r.status_code == 200 and r.json()["trip"]["channel_ids"] == [ids["Mi Discord"]], "un canal ajeno no se puede asignar")
    SENT.clear(); TARGETS.clear()
    checker.run_checks(user_id=ana_id, trigger="manual")
    check(len(SENT) == 1 and TARGETS == [("Mi Discord",)] and "Viaje de Ana" in "\n".join(SENT[0][0]),
          "el aviso va solo al canal asignado al viaje")
    with db.connect() as con:  # varios canales a la vez; uno pausado no recibe
        db.set_trip_channels(con, ana_trip["id"], [ids["Mi Discord"], ids["Mi Telegram"], ids["Discord del grupo"]])
        con.execute(text("DELETE FROM trip_alerts WHERE trip_id = :t"), {"t": ana_trip["id"]})
    ana_c.put(f"/channels/{ids['Discord del grupo']}", {"name": "Discord del grupo", "enabled": False, "config": {"webhook": ""}})
    SENT.clear(); TARGETS.clear()
    checker.run_checks(user_id=ana_id, trigger="manual")
    check(TARGETS == [("Mi Discord", "Mi Telegram")], "avisa a todos los canales asignados y activos (el pausado, no)")
    with db.connect() as con:
        con.execute(text("DELETE FROM trip_alerts WHERE trip_id = :t"), {"t": ana_trip["id"]})
        db.set_trip_channels(con, ana_trip["id"], [])
    SENT.clear(); TARGETS.clear()
    checker.run_checks(user_id=ana_id, trigger="manual")
    check(not SENT, "sin canales asignados no se avisa")
    SENT.clear(); TARGETS.clear()
    checker.run_checks(user_id=admin_id, trigger="manual")
    check(all(t == ("Discord admin",) for t in TARGETS) and not any("Viaje de Ana" in "\n".join(m[0]) for m in SENT),
          "las rondas por usuario no mezclan viajes ni canales")
    admin_trip = admin.get("/trips").json()["trips"][0]
    ana_trips = ana_c.get("/trips").json()["trips"]
    check(admin_trip["channels"] == ["Discord admin"] and ana_trips[0]["channels"] == [],
          "el panel indica a qué canales avisa cada viaje")

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
        db.set_trip_channels(con, ana_trip["id"], [ids["Mi Telegram"]])
    check(ana_c.delete(f"/channels/{ids['Mi Telegram']}").status_code == 204, "Ana borra un canal")
    check(ana_c.get(f"/trips/{ana_trip['id']}").json()["trip"]["channel_ids"] == [],
          "borrar un canal lo quita de los viajes que lo usaban")
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

    # --- desactivar: pierde la sesión y sus viajes dejan de comprobarse
    admin.put(f"/users/{ana_id}", {"username": "ana", "role": "user", "enabled": False})
    check(ana_c.get("/me").status_code == 401, "usuario desactivado: sesión cerrada")
    check(Api().login("ana", "nueva-clave-9").status_code == 401, "usuario desactivado: no puede entrar")
    check(checker.run_checks(user_id=ana_id, trigger="manual") == "empty", "sus viajes no se comprueban")

    # --- eliminar usuario: se lleva sus viajes (y sus tramos) y su avatar
    avatar_path = config.AVATAR_DIR / ana["avatar"]
    check(avatar_path.exists(), "el archivo del avatar existe")
    check(admin.delete(f"/users/{ana_id}").status_code == 204, "eliminar usuario")
    with db.connect() as con:
        check(db.get_user(con, ana_id) is None and db.get_watch(con, ana_watch["id"]) is None, "se borra el usuario y sus viajes")
        n = con.execute(text("SELECT count(*) FROM prices WHERE watch_id = :w"), {"w": ana_watch["id"]}).scalar()
    check(n == 0 and not avatar_path.exists(), "…con su histórico y su avatar")
    check(admin.delete("/session").status_code == 204 and admin.get("/me").status_code == 401, "cerrar sesión")
    check(admin.login("admin", "clave-de-prueba-1").status_code == 200, "volver a entrar")


def trips_flow(admin: Api, admin_chan: int):
    # Un viaje de ida y vuelta SVQ⇄TCI con tramos nuevos. Los dobles dan precio los días +10, +11 y +12; el más
    # barato de cada día entre Vueling (TFN) y Ryanair (TFS) es 55, 30 y 70 € en los dos sentidos.
    d10, d11, d12 = ((TODAY + timedelta(days=n)).isoformat() for n in (10, 11, 12))
    svq_tci = leg("SVQ", "TCI", ["vueling", "ryanair"])
    tci_svq = leg("TCI", "SVQ", ["vueling", "ryanair"])

    bad = admin.post("/trips", {})
    check(bad.status_code == 422 and "tramo de ida" in errors(bad), "un viaje necesita al menos el tramo de ida")
    bad = admin.post("/trips", {"outbound": svq_tci, "return": tci_svq, "min_nights": "5", "max_nights": "2"})
    check("no pueden ser más" in errors(bad), "noches coherentes")
    bad = admin.post("/trips", {"outbound": svq_tci, "return": tci_svq, "min_nights": "0", "max_nights": "99"})
    check("entre 1 y 60" in errors(bad), "viaje: noches fuera de rango")
    r = admin.post("/trips", {"outbound": svq_tci, "return": tci_svq, "min_nights": 1, "max_nights": 2,
                              "max_total": "90", "channel_ids": [admin_chan]})
    trip = r.json()["trip"]
    check(r.status_code == 201 and trip["name"] == "SVQ ⇄ TCI" and trip["warnings"] == [] and trip["kind"] == "flight"
          and trip["outbound"]["origin"] == "SVQ" and trip["return"]["origin"] == "TCI", "crear un viaje de ida y vuelta")
    tid = trip["id"]
    ret_leg = trip["return"]["id"]

    # --- primera ronda del viaje: puebla los precios de los tramos y evalúa el viaje
    SENT.clear()
    checker.run_checks(trip_id=tid, trigger="manual")

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
        check(trips.legs_by_day(con, db.get_settings(), db.get_watch(con, ret_leg), future) == {},
              "los precios viejos de un tramo no cuentan")

    # --- aviso del viaje: total, fechas y un enlace por tramo
    msgs = ["\n".join(m[0]) for m in SENT if "🧳" in m[0][0]]
    check(len(msgs) == 1 and "**85 €**" in msgs[0] and "1 noche" in msgs[0] and "[Ida: Vueling 55 € (SVQ→TFN)](https://" in msgs[0]
          and "[Vuelta: Vueling 30 € (TFN→SVQ)](https://" in msgs[0] and "100 €" not in msgs[0],
          "aviso del viaje con el total y un enlace por tramo (solo lo que cumple la regla)")
    tg = next(m[1] for m in SENT if "🧳" in m[0][0])
    keyboard = json.loads(tg[-1])
    check("<a href" not in "\n".join(tg[:-1]) and "<b>85 €</b>" in "\n".join(tg[:-1])
          and [b["text"].split(" ")[0] for b in keyboard[0]] == ["Ida", "Vuelta"] and keyboard[0][0]["url"].startswith("https://"),
          "aviso del viaje para Telegram: el total en el texto y un botón por tramo")
    trip_msg = next(m[2] for m in SENT if "🧳" in m[0][0])
    check(trip_msg.image and trip_msg.image.startswith(b"\x89PNG"), "el aviso del viaje lleva el calendario en PNG")
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
    form = {"outbound": svq_tci, "return": tci_svq, "min_nights": 1, "max_nights": 2, "max_total": "",
            "discount_pct": "50", "channel_ids": [admin_chan], "name": "Tenerife"}
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
    checker.run_checks(watch_id=ret_leg, trigger="manual")
    check(quotes() == before + 2, "comprobar un tramo recalcula su viaje")
    check(admin.post(f"/trips/{tid}/toggle").json()["trip"]["enabled"] is False, "pausar un viaje")
    before = quotes()
    checker.run_checks(trigger="manual")
    check(quotes() == before, "un viaje en pausa (y sus tramos) no se recalcula en las rondas")
    admin.post(f"/trips/{tid}/toggle")
    detail = admin.get(f"/trips/{tid}").json()
    check(detail["trend"] and detail["alerts"][0]["total"] == 100, "evolución del total y avisos enviados")
    recent = admin.get("/alerts").json()["alerts"]
    check(recent and recent[0]["trip_id"] == tid and recent[0]["trip_name"] == detail["trip"]["name"]
          and recent[0]["total"] == 100, "/alerts: los últimos avisos de los viajes del usuario")

    # --- viaje de solo ida: una combinación por fecha, sin vuelta
    SENT.clear()
    ow = admin.post("/trips", {"outbound": svq_tci, "max_total": "40", "channel_ids": [admin_chan]}).json()["trip"]
    check(ow["return"] is None and ow["warnings"] == [] and ow["name"] == "SVQ → TCI", "crear un viaje de solo ida")
    checker.run_checks(trip_id=ow["id"], trigger="manual")
    q = {x["out_date"]: (x["total"], x["ret"], x["nights"]) for x in admin.get(f"/trips/{ow['id']}").json()["quotes"]}
    check(q == {d10: (55, None, None), d11: (30, None, None), d12: (70, None, None)},
          "solo ida: una combinación por fecha con el precio de la ida, sin vuelta")
    msgs = ["\n".join(m[0]) for m in SENT if "🧳" in m[0][0]]
    check(len(msgs) == 1 and "**30 €**" in msgs[0] and "Vuelta" not in msgs[0] and "Ida:" not in msgs[0]
          and "55 €" not in msgs[0], "aviso de solo ida: un único tramo y solo lo que baja de 40 €")

    # --- tramos que no encajan y borrado en cascada (el viaje posee sus tramos)
    other = admin.post("/trips", {"outbound": svq_tci, "return": leg("MAD", "BCN", ["mockweb"]),
                                  "min_nights": 3, "max_nights": 3}).json()["trip"]
    check(len(other["warnings"]) >= 1 and any("La vuelta sale de MAD" in w for w in other["warnings"]),
          "aviso si los tramos no encajan")
    out_id, oret_id = other["outbound"]["id"], other["return"]["id"]
    admin.delete(f"/trips/{other['id']}")
    with db.connect() as con:
        check(db.get_watch(con, out_id) is None and db.get_watch(con, oret_id) is None,
              "borrar un viaje borra sus tramos (y su histórico)")

    # --- solo para su dueño
    admin.post("/users", {"username": "berta", "password": "clave-de-berta-1", "role": "user"})
    berta = Api()
    berta.login("berta", "clave-de-berta-1")
    check(not berta.get("/trips").json()["trips"], "no ve viajes ajenos")
    for method, path in (("GET", f"/trips/{tid}"), ("GET", f"/trips/{tid}/options?date={d10}"), ("PUT", f"/trips/{tid}"),
                         ("DELETE", f"/trips/{tid}"), ("POST", f"/trips/{tid}/toggle"), ("POST", f"/trips/{tid}/run")):
        check(berta.req(method, path, json=form if method == "PUT" else None).status_code == 404, f"{method} {path} ajeno → 404")
    check(berta.get(f"/watches/{ret_leg}").status_code == 404, "ni el tramo de un viaje ajeno")
    check(not berta.get("/alerts").json()["alerts"] and not berta.get("/runs").json()["runs"],
          "ni los avisos ni las ejecuciones de viajes ajenos")
    users = {u["username"]: u for u in admin.get("/users").json()["users"]}
    check(users["berta"]["n_trips"] == 0 and users["admin"]["n_trips"] >= 2, "la lista de usuarios cuenta sus viajes")
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
    check(res["buscador"]["ok"] and res["buscador"]["coverage"] == "universal" and len(res["buscador"]["routes"]) == 2,
          "el Buscador cubre cualquier ruta")
    asked = len(ASKED)
    admin.post("/route-check", {"origin": "SVQ", "destination": "TCI"})
    check(len(ASKED) == asked, "la cobertura se guarda en caché (no se vuelve a preguntar)")
    r = admin.post("/route-check", {"origin": "andalucia", "destination": "canarias"})
    res = {p["key"]: p for p in r.json()["providers"]}
    check(res["buscador"]["status"] == "too_many" and "como mucho 12" in res["buscador"]["reason"], "límite de pares del Buscador")
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

    # --- tramos con cobertura, escalas y monedas (vía viajes de solo ida)
    bad = oneway(admin, ["vueling", "wizzair"], origin="SVQ", destination="TCI")
    check(bad.status_code == 422 and "Wizz Air no opera esta ruta" in errors(bad), "no se guarda un proveedor que no opera la ruta")
    w = oneway(admin, ["wizzair"], origin="BCN", destination="BUD", max_stops=0, max_total="35",
               name="Barcelona → Budapest", channel_ids=[admin_chan]).json()["trip"]
    leg0 = w["outbound"]
    check(leg0["coverage"][0]["routes"] == ["BCN-BUD"] and leg0["coverage"][0]["checked_at"]
          and leg0["origin_place"]["label"] == "Barcelona (BCN)" and leg0["max_stops"] == 0, "tramo con su cobertura comprobada")
    SENT.clear()
    checker.run_checks(trip_id=w["id"], trigger="manual")
    with db.connect() as con:
        snap = db.latest_snapshot(con, leg0["id"], "wizzair")
    check(snap[0]["price"] == 30 and snap[0]["orig_price"] == 12000 and snap[0]["currency"] == "HUF",
          "precio en moneda original y su equivalente en euros (cambio del BCE)")
    check(any("🧳" in m[0][0] and "**30 €**" in "\n".join(m[0]) for m in SENT),
          "el viaje avisa del total en euros (12.000 HUF → 30 €)")
    detail = admin.get(f"/watches/{leg0['id']}").json()
    check(detail["prices"][0]["currency"] == "HUF" and detail["stats"][0]["best"]["orig_price"] == 12000, "el panel recibe la moneda original")
    bad = oneway(admin, ["buscador"], origin="MAD", destination="BCN", max_stops="7")
    check("máximo de escalas" in errors(bad), "validación del máximo de escalas")

    g = oneway(admin, ["buscador"], origin="MAD", destination="BCN", max_stops="0").json()["trip"]
    gleg = g["outbound"]["id"]
    checker.run_checks(trip_id=g["id"], trigger="manual")
    with db.connect() as con:
        days = {r["flight_date"]: r for r in db.latest_snapshot(con, gleg, "buscador")}
    check((TODAY + timedelta(days=11)).isoformat() not in days and len(days) == 2, "solo directos: el día con escala no cuenta")
    admin.put(f"/trips/{g['id']}", {"outbound": leg("MAD", "BCN", ["buscador"], max_stops=""), "min_nights": 1, "max_nights": 1})
    checker.run_checks(trip_id=g["id"], trigger="manual")
    with db.connect() as con:
        snap = db.latest_snapshot(con, gleg, "buscador")
    check(snap[0]["price"] == 70 and snap[0]["stops"] == 1, "sin límite de escalas: entra y se guarda cuántas tiene")
    admin.delete(f"/trips/{g['id']}")

    # --- un proveedor inactivo (ruta cerrada) no se consulta (watch 1 = tramo de ida del viaje sembrado)
    with db.connect() as con:
        db.update_watch_provider(con, 1, "ryanair", [], False, "2026-01-01T00:00:00")
        before = con.execute(text("SELECT count(*) FROM runs WHERE watch_id = 1 AND provider = 'ryanair'")).scalar()
    checker.run_checks(watch_id=1, trigger="manual")
    with db.connect() as con:
        after = con.execute(text("SELECT count(*) FROM runs WHERE watch_id = 1 AND provider = 'ryanair'")).scalar()
    card = admin.get("/watches/1").json()
    check(after == before and not {s["key"]: s for s in card["stats"]}["ryanair"]["active"],
          "un proveedor inactivo no se consulta y el panel lo marca")

    # --- revalidación semanal: la primera vez sin avisos; después avisa si una ruta se abre o se cierra
    # (watch 1 = tramo de ida del viaje sembrado; los avisos van a los canales de su viaje)
    with db.connect() as con:
        seeded = db.get_watch(con, 1)["trip_id"]
        db.set_trip_channels(con, seeded, [admin_chan])
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
          "aviso al cerrarse una ruta de temporada (a los canales del viaje)")
    r = admin.put(f"/trips/{seeded}", {"outbound": leg("SVQ", "TCI", ["vueling", "ryanair"]),
                                       "return": leg("TCI", "SVQ", ["vueling", "ryanair"]),
                                       "min_nights": 1, "max_nights": 7, "channel_ids": [admin_chan]})
    cov_out = {c["key"]: c for c in r.json()["trip"]["outbound"]["coverage"]}
    check(r.status_code == 200 and cov_out["ryanair"]["active"] is False,
          "al editar el viaje se conserva el proveedor de temporada (inactivo)")
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
    check(r.status_code == 200 and set(res) >= {"vueling", "ryanair", "wizzair", "buscador"}
          and res["vueling"]["status"] == res["buscador"]["status"] == "ok", "prueba de acceso de todos los proveedores")
    check([s["name"] for s in res["ryanair"]["steps"]] == ["Cobertura", "Precios (1 mes)"]
          and "1 destino directo desde SVQ (no incluye BCN)" in res["ryanair"]["steps"][0]["detail"]
          and res["ryanair"]["status"] == "empty", "pasos: cobertura y precios (accesible pero sin precios en esa ruta)")
    check(res["buscador"]["steps"][0]["status"] == "skipped" and res["mockweb"]["steps"][1]["status"] == "skipped",
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
          and last["buscador"]["stops_filter"] and not last["vueling"]["stops_filter"] and "candidates" not in lst,
          "último resultado guardado por proveedor")
    bad = admin.post("/providers/health", {"origin": "TCI", "destination": "SVQ"})
    check(bad.status_code == 422 and "aeropuerto" in errors(bad), "la ruta de prueba debe ser de aeropuertos")

    # --- piezas sueltas: cambio del BCE
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
    return [DayPrice(date.fromisoformat(d["fecha"]), d["precio"], currency=d.get("moneda", "EUR"),
                     departure=d.get("sale"), arrival=d.get("llega"))
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
        self.cookies = requests.cookies.RequestsCookieJar()

    def request(self, method, url, headers=None, timeout=None, **kw):
        self.calls.append((method, url, dict(headers or {}), kw))
        status = BLOCKS.get(url, 200)
        if (headers or {}).get("Sec-Fetch-Mode") == "navigate":  # la portada deja su token XSRF
            self.cookies.set("XSRF-TOKEN", "de-la-portada", domain=stealth.site_of(url).split("//")[1])

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
        self.key, self.calls, self.cookie_calls, self.closed = key, [], [], False
        FakeBrowser.made.append(self)

    def request(self, site, method, url, **kw):
        self.calls.append((site, method, url))
        return browser.BrowserResponse({"status": 200, "url": url, "headers": {"Content-Type": "application/json"},
                                        "text": '{"desde": "chrome"}'})

    def cookie(self, page, name):
        self.cookie_calls.append((page, name))
        return f"chrome:{name}"

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

        # api.cookie(): la cookie de la sesión (tras visitar la portada de esa web), para copiarla en una cabecera.
        with REAL_NEW_SESSION(prov) as s5:
            api = scripted.ScriptApi(prov, s5, None, "t")
            token = api.cookie("XSRF-TOKEN", "https://www.iberiaexpress.com/api/x")
            api.post_json("https://www.iberiaexpress.com/api/x", {"a": 1}, headers={"X-XSRF-TOKEN": token})
            missing = api.cookie("nada")
        calls = s5.shared.client.calls
        check(token == "de-la-portada" and missing is None and calls[-2][1] == "https://www.iberiaexpress.com/"
              and calls[-1][1] == "https://www.iberiaexpress.com/api/x" and calls[-1][2]["X-XSRF-TOKEN"] == "de-la-portada",
              "api.cookie() con la huella de Chrome: visita la portada y da su cookie; post_json acepta cabeceras")

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
        with REAL_NEW_SESSION(always) as s6:
            token = scripted.ScriptApi(always, s6, None, "t").cookie("XSRF-TOKEN")
        chrome = FakeBrowser.made[-1]
        check(token == "chrome:XSRF-TOKEN" and chrome.cookie_calls == [("https://reservas.vueling.com/buscar", "XSRF-TOKEN")]
              and s6.shared.client.calls == [], "api.cookie() con «Siempre Chrome»: la de Chrome, en la BROWSER_PAGE")
        plain = requests.Session()
        plain.cookies.set("csrftoken", "abc", domain="www.ejemplo.test")
        check(scripted.ScriptApi(always, plain, None, "t").cookie("csrftoken") == "abc",
              "api.cookie() sin medidas anti-bot: la de la sesión de requests")
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
            {"fecha": days[0], "precio": 20},
            {"fecha": days[1], "precio": 15, "moneda": "GBP", "sale": "22:40", "llega": "00:15"},
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
    next_day = (date.fromisoformat(days[1]) + timedelta(days=1)).isoformat()
    check(res["n_prices"] == 2 and res["sample"][1] == {"day": days[1], "price": 15, "currency": "GBP", "origin": "SVQ",
                                                        "destination": "TFN", "stops": 0, "departs_at": f"{days[1]}T22:40",
                                                        "arrives_at": f"{next_day}T00:15", "nights": None,
                                                        "offer": None}
          and res["sample"][0]["departs_at"] is None, "prueba del borrador: precios con sus horas (sin los días a 0)")
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
    t = oneway(admin, ["miaero"], origin="SVQ", destination="TFN", max_total="30", name="Script",
               channel_ids=[admin_chan]).json()["trip"]
    w = t["outbound"]
    check(w["coverage"][0]["routes"] == ["SVQ-TFN"], "tramo con el proveedor (cobertura del script)")
    SENT.clear()
    checker.run_checks(trip_id=t["id"], trigger="manual")
    with db.connect() as con:
        snap = db.latest_snapshot(con, w["id"], "miaero")
    check(len(snap) == 2 and snap[0]["currency"] == "GBP" and snap[0]["orig_price"] == 15 and round(snap[0]["price"], 2) == 17.65,
          "la ronda guarda sus precios (en euros y en la moneda original)")
    check(snap[0]["departs_at"] == f"{days[1]}T22:40" and snap[0]["arrives_at"] == f"{next_day}T00:15"
          and snap[1]["departs_at"] is None, "la ronda guarda la salida y la llegada (la del día siguiente)")
    detail = admin.get(f"/watches/{w['id']}").json()
    check(detail["prices"][0]["departs_at"] == f"{days[1]}T22:40", "el detalle devuelve las horas")
    msg = "\n".join(SENT[0][0]) if SENT else ""
    check(f"https://www.miaero.test/vuelos?o=SVQ&d=TFN&f={days[1]}" in msg and "22:40–00:15 (+1)" in msg,
          "el aviso del viaje lleva la plantilla de enlace del tramo y las horas")
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
    check(admin.get(f"/watches/{w['id']}").status_code == 200, "el tramo sigue funcionando sin él")
    r = admin.put(f"/trips/{t['id']}", {"outbound": leg("SVQ", "TFN", ["buscador"]), "min_nights": 1, "max_nights": 1})
    with db.connect() as con:
        kept = db.get_watch(con, w["id"])["coverage"]
    check(r.status_code == 200 and set(kept) == {"buscador", "miaero"} and kept["miaero"]["routes"] == [("SVQ", "TFN")],
          "editar el viaje mientras el proveedor está desactivado no lo quita del tramo")
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
    check(detail.status_code == 200 and detail.json()["watch"]["providers"] == ["buscador"], "la vigilancia ya no lo tiene")
    with db.connect() as con:
        kept = con.execute(text("SELECT count(*) FROM prices WHERE provider = 'miaero'")).scalar()
    check(kept == 2 and admin.get(f"/watches/{w['id']}/charts").status_code == 200, "sus precios se conservan como histórico")
    check(admin.get("/providers/miaero").status_code == 404, "ya no existe")
    admin.delete(f"/watches/{w['id']}")


def bundle_flow(admin: Api):
    """Proveedores incluidos (creados al arrancar), el catálogo y paquetes: exportar, vista previa e importar."""
    lst = admin.get("/providers").json()["providers"]
    check([p["key"] for p in lst] == ["ryanair", "vueling"] and all(p["loaded"] and p["enabled"] for p in lst)
          and lst[0]["updated_by"] == bundle.SEED_USER and lst[0]["source"] == bundle.CATALOG_URL + "providers.fwp"
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
    check(loaded == ["vueling", "ryanair", "wizzair", "aireuropa", "iberiaexpress", "binter"]
          and offered == [bundle.CATALOG_URL + "providers.fwp"] and sorted(p.name for p in bundle.CATALOG_DIR.glob("*.fwp")) == ["providers.fwp"],
          "catálogo: providers.fwp tiene todos los proveedores, sus scripts cargan y el panel lo ofrece")
    check(bundle.raw_url("https://github.com/katarem/flight-watcher/blob/main/app/providers/catalog/sin-verificar.fwp")
          == bundle.raw_url(bundle.CATALOG_URL + "incluidos.fwp") == bundle.CATALOG_URL + "providers.fwp",
          "los enlaces de los paquetes antiguos del catálogo llevan a providers.fwp")
    check(bundle.raw_url("https://raw.githubusercontent.com/katarem/flight-watcher/main/app/providers/catalog/providers.fwp")
          == bundle.CATALOG_URL + "providers.fwp" and "katarem/trip-watch/" in bundle.CATALOG_URL,
          "el enlace del catálogo con el nombre anterior del repositorio (flight-watcher) lleva al de Trip Watch")
    with db.connect() as con:
        db.save_provider_script(con, "vueling", {"source": bundle.OLD_CATALOG_URLS[0] + "providers.fwp"}, "admin")
    bundle.seed()
    with db.connect() as con:
        check(db.get_provider_script(con, "vueling")["source"] == bundle.CATALOG_URL + "providers.fwp",
              "al arrancar, el origen guardado con el nombre anterior del repositorio pasa al nuevo")
    renamed = bundle.dumps([{"key": "x", "code": "def fetch_route(*a):\n    return {}\n"}])
    check(renamed.startswith("#flight-watcher:proveedores v1") and bundle.loads(renamed.replace("#flight-watcher", "#trip-watch", 1))[0]["key"] == "x",
          ".fwp: se sigue escribiendo la cabecera de siempre (paneles anteriores) y se acepta también #trip-watch")

    # --- vista previa desde un enlace (el de GitHub se cambia por el del archivo en bruto) y desde un archivo
    url = "https://github.com/katarem/flight-watcher/blob/main/app/providers/catalog/providers.fwp"
    r = admin.post("/providers/import/preview", {"url": url})
    prev = r.json()
    check(r.status_code == 200 and prev["source"] == bundle.CATALOG_URL + "providers.fwp"
          and [(p["key"], p["status"], p["errors"]) for p in prev["providers"]]
          == [("vueling", "same", []), ("ryanair", "same", []), ("wizzair", "new", []), ("aireuropa", "new", []), ("iberiaexpress", "new", []), ("binter", "new", [])]
          and "def fetch_route" in prev["providers"][2]["code"], "vista previa de un enlace: qué trae y qué haría")
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
    body = {"text": prev["text"], "url": prev["source"], "keys": ["wizzair"]}
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
    check(r.status_code == 200 and r.json()["imported"] == r.json()["created"] == ["wizzair"]
          and lst["wizzair"]["source"] == bundle.CATALOG_URL + "providers.fwp" and lst["wizzair"]["updated_by"] == "admin"
          and "aireuropa" not in lst, "importar desde un enlace solo los elegidos (Wizz Air queda activo)")
    r = admin.post("/providers/import", {"text": fakes.BUSCADOR, "keys": ["buscador"], "password": "clave-de-prueba-1"})
    check(r.status_code == 200 and r.json()["created"] == ["buscador"] and PROVIDERS["buscador"].stops_filter
          and PROVIDERS["buscador"].max_routes == 12, "importar de un archivo: el Buscador (cualquier ruta, con escalas)")
    check(admin.get("/providers").json()["sources"] == [bundle.CATALOG_URL + "providers.fwp"],
          "los enlaces ya usados se recuerdan para volver a importar")
    r = admin.post("/providers/import", {"text": mine, "keys": ["ryanair"], "enabled": True, "password": "clave-de-prueba-1"})
    check(r.status_code == 200 and r.json()["created"] == [] and PROVIDERS["ryanair"].label == "Ryanair (copia)",
          "importar sustituye a uno con la misma clave")
    admin.post("/providers/import", {"url": bundle.CATALOG_URL + "incluidos.fwp", "keys": ["ryanair"], "password": "clave-de-prueba-1"})
    check(PROVIDERS["ryanair"].label == "Ryanair", "volver a importar el original (con el enlace antiguo del catálogo)")


def stays_flow(admin: Api, admin_chan: int):
    """2.1: viajeros (plazas, descuentos, precio por persona) y estancias (proveedores de alojamiento, filtros, viajes
    de solo estancia y con transporte, qué combinaciones se consultan en cada ronda)."""
    d = {n: (TODAY + timedelta(days=n)).isoformat() for n in range(0, 15)}
    r = admin.post("/providers/import", {"text": fakes.CASAS, "keys": ["casas"], "password": "clave-de-prueba-1"})
    check(r.status_code == 200 and PROVIDERS["casas"].kind == "hotel" and PROVIDERS["casas"].coverage == "universal",
          "importar un proveedor de alojamiento")
    meta = admin.get("/meta").json()
    check({k["key"]: k for k in meta["kinds"]}["hotel"]["available"] and "hotel" in {p["kind"] for p in meta["providers"]}
          and {t["key"] for t in meta["stay_options"]["types"]} >= {"hotel", "hostal", "apartment"}
          and {x["key"] for x in meta["party_options"]["regions"]} == {"canarias", "baleares", "ceuta", "melilla"},
          "/meta: el alojamiento, sus filtros y las opciones de los viajeros")

    # --- validación
    stay = {"destination": "Puerto de la Cruz", "providers": ["casas"],
            "filters": {"types": ["hotel", "apartment"], "min_rating": "8"}}
    group = {"travelers": [{"age": None}, {"age": None, "resident": "canarias"}, {"age": 8}], "large_family": ""}
    bad = admin.post("/trips", {"name": "x"})
    check(bad.status_code == 422 and "tramo de ida, la estancia o los dos" in errors(bad), "un viaje necesita ida o estancia")
    bad = admin.post("/trips", {"return": leg("TCI", "SVQ", ["vueling"]), "stay": stay})
    check("necesita también la ida" in errors(bad), "no hay vuelta sin ida")
    bad = admin.post("/trips", {"stay": {"destination": "x", "providers": ["vueling"], "filters": {"types": ["cueva"]}}})
    check("Indica el destino" in errors(bad) and "solo se pueden elegir webs de alojamiento" in errors(bad)
          and "Tipo de alojamiento desconocido" in errors(bad), "validación de la estancia")
    bad = admin.post("/trips", {"stay": stay, "party": {"travelers": [{"age": 5}, {"age": 9, "resident": "marte"}]}})
    check("al menos un adulto" in errors(bad) and "Residencia desconocida en el viajero 2" in errors(bad),
          "validación de los viajeros")
    bad = admin.post("/trips", {"stay": stay, "party": {"travelers": [{"age": "20"}], "large_family": "enorme"}})
    check("edad del viajero 1" in errors(bad) and "familia numerosa" in errors(bad), "edades de 0 a 17 (o adulto)")
    bad = admin.post("/trips", {"stay": stay, "party": {"travelers": [{}] * 10}})
    check("Como mucho 9 viajeros" in errors(bad), "como mucho 9 viajeros")
    bad = admin.post("/trips", {"outbound": leg("SVQ", "TCI", ["casas"])})
    check("Solo se pueden elegir webs de vuelos" in errors(bad), "una web de alojamiento no vale para un vuelo")

    # --- viaje de solo estancia: entradas de +5 a +7, de 2 a 3 noches, 2 adultos y un niño
    SENT.clear()
    r = admin.post("/trips", {"stay": stay, "party": group, "min_nights": 2, "max_nights": 3, "date_from": d[5],
                              "date_to": d[7], "max_per_person": "63", "channel_ids": [admin_chan]})
    t = r.json()["trip"]
    check(r.status_code == 201 and t["outbound"] is None and t["return"] is None and t["kind"] == "hotel"
          and t["stay"]["destination"] == "Puerto de la Cruz" and t["stay"]["filters"]["types"] == ["hotel", "apartment"]
          and t["stay"]["filters"]["min_rating"] == 8 and t["name"] == "Estancia en Puerto de la Cruz"
          and t["party"]["size"] == 3 and t["party"]["label"] == "2 adultos y 1 niño (8 años) · 1 residente en Canarias"
          and t["max_per_person"] == 63, "crear un viaje de solo estancia con sus viajeros")
    stay_id = t["stay"]["id"]
    checker.run_checks(trip_id=t["id"], trigger="manual")
    with db.connect() as con:
        queried = db.stay_checked(con, stay_id, "casas")
    check(len(queried) == 6 and set(queried) == {(d[n], k) for n in (5, 6, 7) for k in (2, 3)},
          "se consultan las entradas de la ventana con cada número de noches")
    detail = admin.get(f"/trips/{t['id']}").json()
    q = {x["out_date"]: x for x in detail["quotes"]}
    first = q[d[5]]
    # Por noche y viajero: hostal 20 € (fuera por el tipo), apartamento 25 € (fuera por la nota), hotel 30 € (+1 €/día).
    check(set(q) == {d[5], d[6], d[7]} and first["total"] == 180 and first["nights"] == 2 and first["ret_date"] == d[7]
          and first["out"] is None and first["ret"] is None and first["stay"]["offer"]["name"] == "Hotel Playa"
          and first["stay"]["link"] == "https://casas.test/hotel-playa" and first["per_person"] == 60
          and first["deal"] == "fixed" and q[d[7]]["total"] == 192 and q[d[7]]["deal"] is None,
          "la estancia más barata que cumple los filtros, con el total y el precio por persona")
    msgs = ["\n".join(m[0]) for m in SENT if "🧳" in m[0][0]]
    check(len(msgs) == 1 and "🏨 Puerto de la Cruz" in msgs[0] and "Hotel Playa (hotel, 4★, 8,6)" in msgs[0]
          and "desayuno" in msgs[0] and "60 €/persona" in msgs[0] and "2 adultos y 1 niño" in msgs[0]
          and "192 €" not in msgs[0] and "Vuelta" not in msgs[0], "aviso de solo estancia con el alojamiento y por persona")
    leg_detail = admin.get(f"/watches/{stay_id}").json()
    check(leg_detail["role"] == "stay" and leg_detail["watch"]["filters"]["min_rating"] == 8
          and leg_detail["watch"]["origin_place"] is None and leg_detail["prices"][0]["nights"] == 2
          and leg_detail["prices"][0]["offer"]["name"] == "Hotel Playa" and len(leg_detail["prices"]) == 6,
          "detalle de la estancia: una fila por entrada y noches, con el alojamiento")
    charts = admin.get(f"/watches/{stay_id}/charts").json()
    check(charts["by_flight_date"]["labels"] == [d[5], d[6], d[7]] and charts["by_flight_date"]["series"]["casas"][0] == 180,
          "gráfica de la estancia: el más barato de cada entrada")

    # --- qué se consulta en cada ronda: primero lo nunca consultado, después lo más antiguo
    trip_row = {"date_from": d[5], "date_to": d[7], "min_nights": 2, "max_nights": 3}
    checked = {(d[5], 2): "2026-01-02", (d[5], 3): "2026-01-01"}
    picked = stays.plan(trip_row, TODAY, None, None, checked, limit=5)
    check(picked[:4] == [(TODAY + timedelta(days=n), k) for n, k in ((6, 2), (6, 3), (7, 2), (7, 3))]
          and picked[4] == (TODAY + timedelta(days=5), 3), "rotación: lo nunca consultado y después lo más antiguo")
    out_days = {d[10]: {"price": 100}, d[11]: {"price": 20}}
    ret_days = {d[12]: {"price": 10}, d[13]: {"price": 500}}
    picked = stays.plan({**trip_row, "date_from": None, "date_to": None, "min_nights": 1, "max_nights": 2},
                        TODAY, out_days, ret_days, {})
    check(picked == [(TODAY + timedelta(days=11), 1), (TODAY + timedelta(days=10), 2), (TODAY + timedelta(days=11), 2)],
          "con transporte: solo las fechas con ida y vuelta, de la más barata a la más cara")
    with db.connect() as con:
        con.execute(text("DELETE FROM stay_queries"))
    real = stays.MAX_QUERIES
    stays.MAX_QUERIES = 4
    try:
        checker.run_checks(trip_id=t["id"], trigger="manual")
        with db.connect() as con:
            check(len(db.stay_checked(con, stay_id, "casas")) == 4, "como mucho MAX_QUERIES combinaciones por ronda")
    finally:
        stays.MAX_QUERIES = real

    # --- vuelos para varios viajeros: la web que no los admite da el de un adulto (× plazas, estimado)
    SENT.clear()
    svq_tci, tci_svq = leg("SVQ", "TCI", ["vueling", "ryanair"]), leg("TCI", "SVQ", ["vueling", "ryanair"])
    two = {"travelers": [{"age": None}, {"age": None}]}
    full = admin.post("/trips", {"outbound": svq_tci, "return": tci_svq, "stay": {**stay, "filters": {}},
                                 "party": two, "min_nights": 1, "max_nights": 2, "channel_ids": [admin_chan],
                                 "max_total": "300"}).json()["trip"]
    check(full["name"] == "SVQ ⇄ TCI · Puerto de la Cruz" and full["stay"] and full["return"],
          "un viaje con ida, vuelta y estancia")
    checker.run_checks(trip_id=full["id"], trigger="manual")
    quotes = {x["out_date"]: x for x in admin.get(f"/trips/{full['id']}").json()["quotes"]}
    best = quotes[d[10]]
    # Ida y vuelta: 55, 30 y 70 € por adulto los días +10, +11 y +12 (× 2); alojamiento: el hostal (sin filtros),
    # 20 € por noche y viajero.
    check(best["out"]["price"] == 110 and best["out"]["estimated"] and best["ret"]["price"] == 60
          and best["stay"]["price"] == 40 and best["total"] == 210 and best["nights"] == 1 and best["per_person"] == 105
          and best["stay"]["offer"]["name"] == "Hostal Centro", "total = ida + vuelta + alojamiento, para los dos")
    msgs = ["\n".join(m[0]) for m in SENT if "🧳" in m[0][0]]
    check(len(msgs) == 1 and "[Alojamiento: Casas de prueba 40 € · Hostal Centro" in msgs[0]
          and "[Ida: Vueling 110 € (SVQ→TFN)]" in msgs[0] and "transporte estimado" in msgs[0]
          and "105 €/persona" in msgs[0], "aviso con el desglose de transporte y alojamiento")
    with db.connect() as con:
        link = trips.stays_by_combo(con, db.get_settings(), db.get_trip(con, full["id"]),
                                    db.trip_legs(con, full["id"])["stay"], trips.local_now(db.get_settings()))[(d[10], 1)]["link"]
    check(link == f"https://casas.test/buscar?q=Puerto%20de%20la%20Cruz&entrada={d[10]}&salida={d[11]}&adultos=2",
          "sin enlace propio de la oferta, la plantilla del proveedor con entrada, salida y viajeros")

    # --- una web que admite viajeros da el precio de todos (sin estimar)
    check(PROVIDERS["buscador"].party_aware and not PROVIDERS["vueling"].party_aware, "qué webs admiten viajeros")
    bus = oneway(admin, ["buscador"], origin="MAD", destination="BCN", max_stops=None).json()["trip"]
    admin.put(f"/trips/{bus['id']}", {"outbound": leg("MAD", "BCN", ["buscador"], max_stops=None), "party": two})
    checker.run_checks(trip_id=bus["id"], trigger="manual")
    with db.connect() as con:
        snap = db.latest_snapshot(con, bus["outbound"]["id"], "buscador")
    check(snap[0]["price"] == 140 and not snap[0]["estimated"], "el Buscador recibe los viajeros: precio de los dos")

    # --- editar: quitar la estancia la borra (con su histórico); añadirla a un viaje de solo ida
    r = admin.put(f"/trips/{full['id']}", {"outbound": svq_tci, "return": tci_svq, "party": two, "min_nights": 1,
                                           "max_nights": 2})
    with db.connect() as con:
        check(r.json()["trip"]["stay"] is None and db.get_watch(con, full["stay"]["id"]) is None,
              "quitar el alojamiento borra la estancia")
    r = admin.put(f"/trips/{bus['id']}", {"outbound": leg("MAD", "BCN", ["buscador"], max_stops=None), "stay": stay,
                                          "min_nights": 2, "max_nights": 2})
    check(r.status_code == 200 and r.json()["trip"]["stay"]["destination"] == "Puerto de la Cruz"
          and r.json()["trip"]["party"]["size"] == 1, "añadir alojamiento a un viaje de solo ida (y volver a un viajero)")
    with db.connect() as con:
        check(db.get_trip(con, bus["id"])["party"] is None, "un adulto sin descuentos no se guarda (es el de por defecto)")

    # --- la estancia en la prueba de acceso y en la prueba del editor
    res = {x["key"]: x for x in admin.post("/providers/health", {"providers": ["casas"]}).json()["results"]}["casas"]
    check(res["status"] == "ok" and res["route"] == "Puerto de la Cruz" and res["steps"][0]["name"] == "Alojamientos (una búsqueda)"
          and "3 alojamientos" in res["steps"][0]["detail"], "prueba de acceso de un proveedor de alojamiento")
    casas = admin.get("/providers/casas").json()["provider"]
    _r, result, events = run_test(admin, {**casas, "origin": "Ningún sitio", "password": "clave-de-prueba-1"})
    check(result["status"] == "empty" and result["route"] == "Ningún sitio" and "Define fetch_stay" in console_text(events)
          and "script: busco Ningún sitio" in console_text(events),
          "prueba del editor de un alojamiento: sin resultados en un destino desconocido")
    _r, result, _e = run_test(admin, {**casas, "password": "clave-de-prueba-1"})
    check(result["status"] == "ok" and result["sample"][0]["offer"]["name"] and result["sample"][0]["nights"] == 2,
          "prueba del editor de un alojamiento: muestra de ofertas")
    bad = admin.put("/providers/casas", {**casas, "health_origin": ""})
    check(bad.status_code == 422 and "destino de prueba" in errors(bad), "un alojamiento necesita su destino de prueba")
    check("fetch_stay" in admin.get("/providers").json()["templates"]["hotel"], "plantilla del editor para alojamiento")
    check(party.load(None).simple and party.load('{"travelers": [{"age": 1}, {}]}').seats == 1,
          "un bebé no ocupa plaza")


def kinds_flow(admin: Api):
    """Tipos de transporte y de proveedor (1.9) y lugares genéricos (estaciones, puertos y la ciudad que los agrupa)."""
    meta = admin.get("/meta").json()
    by_kind = {k["key"]: k for k in meta["kinds"]}
    check(by_kind["flight"]["available"] and "section" not in by_kind["flight"] and not by_kind["train"]["available"]
          and by_kind["train"]["since"] == "3.1" and {p["kind"] for p in meta["providers"]} == {"flight"},
          "/meta: transportes (solo vuelos disponibles) y el tipo de cada proveedor")
    bad = oneway(admin, ["vueling"], origin="SVQ", destination="MAD", kind="train")
    check(bad.status_code == 422 and "llegan en la 3.1" in errors(bad), "aún no hay viajes de trenes")
    check("Tipo de transporte desconocido" in errors(admin.post("/trips", {"outbound": {"kind": "cohete"}})), "transporte desconocido")
    check(all(t["kind"] == "flight" for t in admin.get("/trips").json()["trips"]),
          "los viajes son de vuelos (el transporte se deriva del tramo de ida)")

    # --- lugares de otros transportes: un puerto en Tenerife y una estación en Sevilla (datos de prueba)
    data = Path(tempfile.mkdtemp(prefix="fw-places-"))
    for name in ("airports.csv", "countries.csv"):
        (data / name).write_text((places.DATA_DIR / name).read_text("utf-8"), "utf-8")
    (data / "ports.csv").write_text("code,name,city,city_code,country,keywords\n"
                                    "ESSCT,Puerto de Santa Cruz,Santa Cruz de Tenerife,TCI,ES,muelle\n", "utf-8")
    (data / "stations.csv").write_text("code,name,city,city_code,country,keywords\n"
                                       "SVQSJ,Sevilla-Santa Justa,Sevilla,,ES,tren\nbad,Mal código,,,ES,\n", "utf-8")
    real_dir = places.DATA_DIR
    places.DATA_DIR = data
    places.catalog.cache_clear()
    try:
        tci = places.get("TCI")
        check(tci.nodes_for("flight") == ("TFN", "TFS") and tci.nodes_for("ship") == ("ESSCT",)
              and "Puertos: ESSCT" in tci.detail and set(tci.modes) == {"flight", "ship"},
              "la ciudad agrupa sus aeropuertos y su puerto")
        check(places.routes("TCI", "SVQ") == [("TFN", "SVQ"), ("TFS", "SVQ")] and places.nodes("TCI", "ship") == ("ESSCT",)
              and places.routes("TCI", "SVQSJ", "ship") == [] and places.routes("TCI", "SVQSJ", "train") == []
              and places.get("svqsj").kind == "station" and places.get("BAD") is None,
              "las rutas de una vigilancia solo usan lugares de su transporte")
        flights = [p["code"] for p in places.search("tenerife", 10, "flight")]
        ships = [p["code"] for p in places.search("tenerife", 10, "ship")]
        check("ESSCT" not in flights and "TFN" in flights and "TCI" in flights and ships[:2] == ["TCI", "ESSCT"]
              and "TFN" not in ships, "el autocompletado filtra por el transporte")
        r = admin.get("/places", params={"q": "santa justa", "kind": "flight"}).json()["places"]
        check(r == [] and admin.get("/places", params={"q": "santa justa"}).json()["places"][0]["kind_label"] == "Estación",
              "API de lugares con el transporte")
        check("Estaciones: SVQSJ" in places.get("ES").detail, "el país incluye sus lugares de cada transporte")
        bad = admin.post("/route-check", {"origin": "SVQSJ", "destination": "TCI"})
        check(bad.status_code == 422 and "no tiene ningún aeropuerto" in errors(bad), "una estación no vale en una vigilancia de vuelos")

        # --- proveedores por tipo: uno de trenes no sale en las vigilancias de vuelos
        body = {"key": "renfe_prueba", "kind": "train", "label": "Tren de prueba", "color": "#7c3aed", "coverage": "universal",
                "health_origin": "SVQSJ", "health_destination": "M0001", "min_interval": "0", "password": "clave-de-prueba-1",
                "code": "def fetch_route(api, origin, destination, start, max_months):\n    return {}\n"}
        r = admin.post("/providers", body)
        check(r.status_code == 201 and r.json()["provider"]["kind"] == "train" and r.json()["provider"]["kind_label"] == "Trenes"
              and PROVIDERS["renfe_prueba"].kind == "train", "crear un proveedor de trenes")
        check("Tren de prueba" not in {p["label"] for p in admin.post("/route-check", {"origin": "SVQ", "destination": "TCI"}).json()["providers"]},
              "la comprobación de rutas de vuelos no lo consulta")
        bad = oneway(admin, ["renfe_prueba"], origin="SVQ", destination="TCI")
        check(bad.status_code == 422 and "Solo se pueden elegir webs de vuelos" in errors(bad), "un viaje de vuelos no usa un proveedor de trenes")
        bad = admin.post("/providers", {**body, "key": "otro", "health_origin": "TFN"})
        check(bad.status_code == 422 and "tipo estación" in errors(bad), "la ruta de prueba es de lugares de su transporte")
        bad = admin.post("/providers", {**body, "key": "hotel_x", "kind": "hotel", "health_origin": "Tenerife"})
        check(bad.status_code == 422 and "Falta definir `fetch_stay`" in errors(bad),
              "un proveedor de alojamiento tiene su propio contrato (fetch_stay)")
        text_fwp = admin.get("/providers/export", params={"keys": "renfe_prueba"}).text
        check('"kind": "train"' in text_fwp and bundle.loads(text_fwp)[0]["kind"] == "train", "el .fwp guarda el tipo")
        old = bundle.loads(text_fwp.replace('"kind": "train", ', ""))
        check("kind" not in old[0] and bundle.values(old[0])["kind"] == "flight", "un .fwp antiguo (sin tipo) es de vuelos")
        check(admin.delete("/providers/renfe_prueba").status_code == 204, "borrar el de trenes")
        vueling = admin.get("/providers/vueling").json()["provider"]
        bad = admin.put("/providers/vueling", {**vueling, "kind": "ship"})
        check(bad.status_code == 422 and "No se puede cambiar el tipo" in errors(bad), "no se cambia el tipo de un proveedor en uso")
    finally:
        places.DATA_DIR = real_dir
        places.catalog.cache_clear()


def notify_flow():
    """Cómo se pinta un aviso en cada canal: límites de Discord, botones de Telegram (y su plan B) e imagen."""
    big = notify.Message("✈️ Muchas fechas", url="https://panel.example.com/flights/1", summary="SVQ→TCI",
                         image=b"\x89PNG...")
    for n in range(3):
        sec = notify.Section(f"Web {n}", "#e8a800", "habitual ≈ 50 €")
        sec.items = [notify.Item(f"lun {i:02d}/11/2026", f"{30 + i} €", "directo · 06:35–08:10",
                                 [("fecha", f"https://web{n}.example.com/{i}")], [f"{i:02d}/11 · {30 + i} €"]) for i in range(30)]
        big.sections.append(sec)
    payloads = notify.discord_payloads(big)
    embeds = [e for p in payloads for e in p["embeds"]]
    check(len(payloads) >= 1 and all(len(p["embeds"]) <= 10 and sum(notify._embed_size(e) for e in p["embeds"]) <= 6000 for p in payloads)
          and all(len(e.get("fields", [])) <= 25 for e in embeds) and sum(len(e.get("fields", [])) for e in embeds) == 90
          and embeds[0]["image"]["url"] == "attachment://calendario.png" and embeds[1]["color"] == 0xE8A800,
          "Discord: embeds y campos dentro de los límites, con la imagen y el color de cada web")
    texts, keyboard = notify.telegram_parts(big)
    check(all(len(t) <= 4096 for t in texts) and sum(len(r) for r in keyboard) <= 100
          and keyboard[-1] == [{"text": "📊 Abrir en el panel", "url": "https://panel.example.com/flights/1"}],
          "Telegram: textos y botones dentro de los límites, con el del panel al final")
    check(notify._valid_button_url("https://vuelos.example.com/x") and not notify._valid_button_url("http://localhost:8000/x")
          and not notify._valid_button_url("http://nas.local/x"), "Telegram: solo botones con URL que admite")

    calls = []

    class Resp:
        def __init__(self, status, body=""):
            self.status_code, self.text = status, body

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(str(self.status_code))

    def fake_tg(config, method, data, files=None):
        calls.append((method, data, files))
        if "reply_markup" in data:
            return Resp(400, '{"ok":false,"description":"Bad Request: BUTTON_URL_INVALID"}')
        return Resp(200)

    real_tg, notify._tg = notify._tg, fake_tg
    try:
        small = notify.Message("✈️ Vigilancia", url="http://192.168.1.10:8000/flights/1", image=b"\x89PNG",
                               sections=[notify.Section("Vueling", "#e8a800", items=[
                                   notify.Item("lun 03/11/2026", "30 €", "", [("lun 03/11/2026", "https://v.example.com/a?b=1&c=2")],
                                               ["03/11 · 30 €"])])])
        notify.KINDS["telegram"]["send"]({"token": "1:x", "chat_id": "42"}, small)
        check([c[0] for c in calls] == ["sendPhoto", "sendPhoto"] and "reply_markup" not in calls[1][1]
              and '<a href="https://v.example.com/a?b=1&amp;c=2">' in calls[1][1]["caption"],
              "Telegram: si rechaza un botón, repite con los enlaces en el texto (la foto, con el texto de pie)")
    finally:
        notify._tg = real_tg

    posted = []
    real_post = notify.requests.post
    notify.requests.post = lambda url, **kw: posted.append((url, kw)) or Resp(204)
    try:
        notify.KINDS["discord"]["send"]({"webhook": "https://discord.com/api/webhooks/1/x"}, small)
    finally:
        notify.requests.post = real_post
    check(len(posted) == 1 and "files[0]" in posted[0][1]["files"] and json.loads(posted[0][1]["data"]["payload_json"])["embeds"],
          "Discord: la imagen va adjunta en el mismo mensaje que los embeds")
    sample = notify.sample_message("https://panel.example.com")
    check(sample.image.startswith(b"\x89PNG") and sample.sections[0].items, "aviso de ejemplo para probar un canal")
    check(images.calendar_png({}, set(), "x") is None and images.levels({date(2026, 1, d): float(d) for d in range(1, 9)})[date(2026, 1, 1)] == 1,
          "calendario: sin precios no hay imagen; niveles por cuartil")


def main():
    with TestClient(app) as raw:
        client = Api(raw)

        # --- el panel compilado se sirve desde WEB_DIR y el enrutado lo resuelve el navegador
        r = raw.get("/")
        check(r.status_code == 200 and 'id="root"' in r.text and r.headers["cache-control"] == "no-cache", "GET / entrega el panel")
        check('id="root"' in raw.get("/watches/12").text and 'id="root"' in raw.get("/admin/users").text
              and 'id="root"' in raw.get("/trips/3/legs/12").text,
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
        check(client.get("/me").status_code == 401 and client.get("/trips").status_code == 401, "la API responde 401 sin sesión")
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
        check(client.get("/docs").status_code == 200 and "/api/v1/trips" in client.get("/openapi.json").json()["paths"],
              "documentación de la API con sesión")
        check(raw.get("/index.html").headers["cache-control"] == "no-cache", "index.html nunca se queda en caché")
        meta = client.get("/meta").json()
        check(meta["version"] and {p["key"] for p in meta["providers"]} >= {"vueling", "ryanair"}, "metadatos del panel")
        bundle_flow(client)

        # --- lecturas base
        for path in ("/trips", "/alerts", "/runs", "/settings", "/debug/files", "/users", "/channels", "/status"):
            check(client.get(path).status_code == 200, f"GET {path}")
        cards = client.get("/trips").json()["trips"]
        check(len(cards) == 1 and cards[0]["name"] == "Sevilla ⇄ Tenerife"
              and (cards[0]["outbound"]["origin"], cards[0]["outbound"]["destination"]) == ("SVQ", "TCI")
              and (cards[0]["return"]["origin"], cards[0]["return"]["destination"]) == ("TCI", "SVQ"),
              "viaje inicial sembrado (SVQ ⇄ TCI con sus dos tramos)")
        out_leg, ret_leg = cards[0]["outbound"]["id"], cards[0]["return"]["id"]

        # --- ronda: se consultan y guardan los precios de los tramos; los chollos se evalúan por viaje
        #     (el formato del aviso lo cubre trips_flow). Aquí: expansión de TCI y aeropuerto real.
        with db.connect() as con:
            admin_chan = db.create_channel(con, admin_id, "discord", "Discord admin", {"webhook": "https://discord.com/api/webhooks/1/admin"})
        check(checker.run_checks(trigger="manual") == "done", "run_checks termina")
        with db.connect() as con:
            routes_saved = {(r[0], r[1], r[2]) for r in con.execute(text("SELECT provider, origin, destination FROM prices"))}
        check(("vueling", "SVQ", "TFN") in routes_saved and ("ryanair", "SVQ", "TFS") in routes_saved
              and not any(o == "TCI" or d == "TCI" for _, o, d in routes_saved),
              "TCI se expande a TFN/TFS y se guarda el aeropuerto real")
        runs = client.get("/runs").json()["runs"]
        check(all(r["ok"] for r in runs) and not any("La web no devolvió" in (r["error"] or "") for r in runs),
              "una ruta no operada dentro de TCI no cuenta como error")
        check({(r["trip_id"], r["trip_name"]) for r in runs} == {(cards[0]["id"], "Sevilla ⇄ Tenerife")},
              "cada ejecución lleva el viaje de su tramo")

        # --- detalle de un tramo (lo pinta el detalle de su viaje), calendario y gráficas
        detail = client.get(f"/watches/{out_leg}").json()
        day = (TODAY + timedelta(days=11)).isoformat()  # el más barato de la ronda simulada
        check(detail["prices"][0]["flight_date"] == day and detail["prices"][0]["price"] == 30,
              "precios de la última comprobación del tramo (del más barato)")
        stats = {s["key"]: s for s in detail["stats"]}
        check("tickets.vueling.com/booking" in stats["vueling"]["best"]["link"] and "d=TFN" in stats["vueling"]["best"]["link"],
              "el detalle del tramo muestra el enlace con fecha y aeropuerto real")
        check("originIata=SVQ&destinationIata=TFS" in stats["ryanair"]["best"]["link"]
              and stats["ryanair"]["best"]["route"] == "SVQ→TFS", "Ryanair enlaza a TFS dentro de TCI")
        check(detail["checks"], "historial de comprobaciones del tramo")
        charts = client.get(f"/watches/{out_leg}/charts").json()
        check(charts["by_flight_date"]["labels"] and "vueling" in charts["min_over_time"]["series"], "API de gráficas")
        hist = client.get(f"/watches/{out_leg}/date-history", params={"date": day}).json()
        check(len(hist["labels"]) >= 1, "API del historial de una fecha")
        check(ret_leg and client.get(f"/watches/{ret_leg}").status_code == 200, "el tramo de vuelta también tiene detalle")

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

        # --- CRUD de viajes (sus tramos se crean inline; un viaje de solo ida es un único tramo)
        bad = oneway(client, [], origin="S1", destination="TFN")
        check(bad.status_code == 422 and "código IATA" in errors(bad) and "al menos un proveedor" in errors(bad), "validación del formulario")
        bad = client.post("/trips", {"outbound": {"origin": 3, "providers": "x"}})
        check(bad.status_code == 422 and "Datos no válidos" in errors(bad), "tipos incorrectos → 422 en castellano")
        bad = oneway(client, ["vueling"], origin="agp", destination="bcn")
        check(bad.status_code == 422 and "Vueling no opera esta ruta" in errors(bad), "un proveedor que no opera la ruta no se puede elegir")
        r = oneway(client, ["mockweb", "nope"], origin="agp", destination="bcn", max_total="25,5")
        check(r.status_code == 201, "crear un viaje de solo ida")
        new = r.json()["trip"]
        check(new["outbound"]["origin"] == "AGP" and new["outbound"]["destination"] == "BCN" and new["max_total"] == 25.5
              and new["outbound"]["providers"] == ["mockweb"] and new["return"] is None and new["name"] == "AGP → BCN",
              "IATA en mayúsculas, total con coma, proveedores desconocidos fuera y sin tramo de vuelta")
        r = client.post(f"/trips/{new['id']}/toggle")
        check(r.status_code == 200 and r.json()["trip"]["enabled"] is False, "pausar/reanudar")
        check(client.delete(f"/trips/{new['id']}").status_code == 204 and client.get(f"/trips/{new['id']}").status_code == 404, "eliminar")
        st = client.get("/status").json()
        check(st["running"] is False and st["current"] == "" and st["next_run"], "estado de ejecución y próxima ronda")
        check(sum(1 for r in client.get("/runs").json()["runs"] if r["ok"]) >= 2, "historial de ejecuciones")

        kinds_flow(client)
        notify_flow()
        tid = trips_flow(client, admin_chan)
        providers_flow(client, admin_id, admin_chan)
        scripts_flow(client, admin_chan)
        stays_flow(client, admin_chan)
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
