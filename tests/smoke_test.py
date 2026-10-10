"""Test de humo sin red ni navegador real: `python -m tests.smoke_test`

Sustituye el navegador y los proveedores por datos simulados y comprueba de extremo a extremo:
guardado de precios, reglas de aviso, enlaces con fecha, mensajes, la API del panel (sesión, permisos,
vigilancias, gráficas, canales, usuarios, ajustes), lugares y cobertura de rutas, escalas y monedas, la
revalidación semanal, la prueba de acceso a los proveedores y que el servidor entrega el panel compilado.
"""
import base64
import os
import sqlite3
import tempfile
import threading
import time
import json
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

from app import checker, config, coverage, db, fx, places  # noqa: E402
from app.main import app  # noqa: E402
from app.providers import PROVIDERS, DayPrice  # noqa: E402
from app.providers.base import Provider  # noqa: E402
from app.providers.extract import parse_day, parse_price, walk_json  # noqa: E402
from app.providers.google import parse_response, request_body  # noqa: E402

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
          and last["google"]["verified"] is None and lst["candidates"], "último resultado guardado por proveedor")
    bad = admin.post("/providers/health", {"origin": "TCI", "destination": "SVQ"})
    check(bad.status_code == 422 and "aeropuerto" in errors(bad), "la ruta de prueba debe ser de aeropuertos")
    r = admin.post("/providers/health", {"providers": [], "candidates": True, "browser": True})
    cands = {c["key"]: c for c in r.json()["candidates"]}
    check(cands["iberia"]["status"] == "blocked" and "Akamai" in cands["iberia"]["steps"][0]["detail"]
          and cands["volotea"]["status"] == "ok" and "Cloudflare" in cands["volotea"]["steps"][0]["detail"]
          and len(cands["easyjet"]["steps"]) == 2, "aerolíneas en estudio: portada sin y con navegador, con anti-bot detectado")

    # --- piezas sueltas: respuesta de Google Flights y cambio del BCE
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

        # --- ajustes: plantilla de enlace personalizada y validaciones
        r = client.put("/settings", {
            "schedule_hours": "8,20", "schedule_minute": "30", "timezone": "Europe/Madrid", "max_months": "11",
            "min_samples": "30", "retention_days": "400", "headless": "1", "debug": False,
            "link_ryanair": "https://www.ryanair.com/x?o={origin}&d={destination}&f={date_dmy}", "link_vueling": "",
        })
        check(r.status_code == 200 and r.json()["values"]["schedule_hours"] == "8,20", "guardar ajustes")
        s = db.get_settings()
        check(s["schedule_hours"] == "8,20" and s["debug"] == "0", "ajustes persistidos")
        with db.connect() as con:
            check(len(db.list_channels(con, admin_id)) == 1, "los ajustes no tocan los canales del usuario")
        bad = client.put("/settings", {"schedule_hours": "99", "schedule_minute": "0", "timezone": "Nope/Zone",
                                       "max_months": "11", "min_samples": "30", "retention_days": "400"})
        check(bad.status_code == 422 and "Las horas deben ser" in errors(bad) and "Zona horaria desconocida" in errors(bad), "validación de ajustes")
        link = PROVIDERS["ryanair"].build_link(s["link_ryanair"], "SVQ", "TFN", date(2026, 10, 24))
        check(link.endswith("f=24/10/2026"), "plantilla de enlace personalizada")

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

        providers_flow(client, admin_id, admin_chan)
        users_flow(client, admin_id)

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
