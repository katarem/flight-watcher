"""Test de humo sin red ni navegador real: `python -m tests.smoke_test`

Sustituye el navegador y los proveedores por datos simulados y comprueba de extremo a extremo:
guardado de precios, reglas de aviso, enlaces con fecha, mensajes, panel, gráficas y ajustes.
"""
import base64
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from urllib.parse import unquote

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="fw-test-")
os.environ["PANEL_USER"], os.environ["PANEL_PASSWORD"] = "admin", "clave-de-prueba-1"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import checker, config, db, notify  # noqa: E402
from app.main import app  # noqa: E402
from app.providers import PROVIDERS, CalendarProvider, DayPrice  # noqa: E402
from app.providers.extract import JsonCollector, parse_day, parse_price, walk_json  # noqa: E402

TODAY = date.today()


# ------------------------------------------------------------- doble de navegador
class FakePage:
    def set_default_timeout(self, _): ...
    def screenshot(self, **_): ...


class FakeContext:
    def new_page(self):
        return FakePage()

    def close(self): ...


class FakeBrowser:
    def new_context(self, **_):
        return FakeContext()


@contextmanager
def fake_session(_settings):
    yield FakeBrowser()


checker.browser_session = fake_session

class MockWebProvider(CalendarProvider):
    """Proveedor con navegador (como los que no tienen API) para cubrir esa rama del checker."""
    key, label = "mockweb", "MockWeb"


PROVIDERS["mockweb"] = MockWebProvider()
PRICES = {"vueling": [55, 30, 70], "ryanair": [60, 45, 80], "mockweb": [120, 95, 140]}  # 2.º día, el más barato
# Con TCI el checker consulta TFN y TFS: Vueling solo opera TFN y Ryanair solo TFS (como en la realidad).
OPERATES = {"vueling": {"TFN"}, "ryanair": {"TFS"}}


def make_fetch(key):
    def fetch(self, page, origin, destination, max_months, debug_dir=None):
        if key in OPERATES and not OPERATES[key] & {origin, destination}:
            return []
        return [DayPrice(TODAY + timedelta(days=10 + i), p, origin=origin, destination=destination)
                for i, p in enumerate(PRICES[key])]
    return fetch


for k, prov in PROVIDERS.items():
    type(prov).fetch_prices = make_fetch(k)

SENT = []
TARGETS = []  # nombres de los canales a los que iba cada aviso

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==")


def fake_send(channels, lines):
    SENT.append((list(lines["markdown"]), list(lines["html"])))
    TARGETS.append(tuple(c["name"] for c in channels))
    return [c["name"] for c in channels], []


notify.send = fake_send


def check(cond, msg):
    print(("  OK  " if cond else " FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=False)


def users_flow(admin_client, admin_id):
    # --- CRUD de usuarios (solo admin)
    check(admin_client.get("/admin/users").status_code == 200 and "@admin" in admin_client.get("/admin/users").text, "lista de usuarios")
    bad = admin_client.post("/admin/users", data={"username": "A!", "password": "corta", "role": "user"})
    check("3-32 caracteres" in bad.text and "al menos 8" in bad.text, "validación al crear usuario")
    bad = admin_client.post("/admin/users", data={"username": "ADMIN", "password": "una-clave-larga", "role": "user"})
    check("Ya existe" in bad.text, "usuario duplicado (sin distinguir mayúsculas)")
    r = admin_client.post("/admin/users", data={"username": "Ana", "display_name": "Ana García", "password": "clave-de-ana-1",
                                                "role": "user", "enabled": "1"},
                          files={"avatar": ("a.png", PNG, "image/png")}, follow_redirects=False)
    check(r.status_code == 303, "crear usuario con avatar")
    with db.connect() as con:
        ana = db.get_user_by_username(con, "ana")
    check(ana and ana["role"] == "user" and ana["avatar"] and ana["avatar"].endswith(".png"), "usuario y avatar guardados")
    got = admin_client.get(f"/avatars/{ana['avatar']}")
    check(got.status_code == 200 and got.content == PNG and got.headers["content-type"] == "image/png", "el avatar se sirve")
    users_page = admin_client.get("/admin/users").text
    check(f"/avatars/{ana['avatar']}" in users_page, "la lista muestra el avatar")
    check(re.search(r'<img class="avatar sm"[^>]*width="\d+" height="\d+"', users_page), "el avatar lleva tamaño propio sin CSS")
    check(admin_client.get("/avatars/../../etc/passwd").status_code == 404 and admin_client.get("/avatars/nope.png").status_code == 404,
          "avatar inexistente → 404")
    r = admin_client.post(f"/admin/users/{ana['id']}/edit", data={"username": "ana", "display_name": "Ana García", "role": "user", "enabled": "1"},
                          files={"avatar": ("x.png", b"<svg onload=alert(1)/>", "image/png")}, follow_redirects=False)
    check("no se guardó" in unquote(r.headers["location"]), "un archivo que no es imagen se rechaza con aviso")
    with db.connect() as con:
        check(db.get_user(con, ana["id"])["avatar"] == ana["avatar"], "el avatar anterior se conserva")

    # --- el usuario normal: sesión propia, sin acceso a lo de admin y con sus propias vigilancias
    ana_client = TestClient(app)
    check(login(ana_client, "ana", "clave-de-ana-1").status_code == 303, "login de usuario normal")
    for path in ("/admin/users", "/admin/users/new", "/settings", "/debug"):
        check(ana_client.get(path).status_code == 403, f"{path} prohibido para un usuario normal")
    check(ana_client.post("/admin/users", data={"username": "x1x", "password": "12345678"}).status_code == 403, "crear usuarios prohibido")
    home = ana_client.get("/").text
    check("Sevilla → Tenerife" not in home and "/admin/users" not in home and "Ajustes" not in home, "no ve vigilancias ni menús de admin")
    check("Ana García" in home, "la cabecera muestra su nombre y su avatar")
    check(admin_client.get("/").text.count("Usuarios") >= 1, "el admin sí ve el menú de usuarios")
    for path in ("/watches/1", "/watches/1/edit", "/api/watches/1/charts", "/api/watches/1/date-history?date=2026-01-01"):
        check(ana_client.get(path).status_code == 404, f"{path} de otro usuario → 404")
    for path in ("/watches/1/delete", "/watches/1/toggle", "/watches/1/run"):
        check(ana_client.post(path, follow_redirects=False).status_code == 404, f"POST {path} de otro usuario → 404")
    check(admin_client.get("/watches/1").status_code == 200, "el dueño sigue accediendo")
    check(ana_client.get("/api/status").json()["current"] == "", "estado de ejecución sin nombres ajenos")

    r = ana_client.post("/watches", data={"name": "Vigilancia de Ana", "origin": "MAD", "destination": "BCN",
                                          "providers": ["mockweb"], "max_price": "100", "enabled": "1"},
                        follow_redirects=False)
    check(r.status_code == 303, "Ana crea su vigilancia")
    with db.connect() as con:
        ana_watch = [w for w in db.list_watches(con) if w["name"] == "Vigilancia de Ana"][0]
    check(ana_watch["user_id"] == ana["id"], "la vigilancia pertenece a Ana")
    check("Vigilancia de Ana" in ana_client.get("/").text and "Vigilancia de Ana" not in admin_client.get("/").text,
          "cada uno ve solo las suyas en el panel")
    check(admin_client.get(f"/watches/{ana_watch['id']}").status_code == 404, "ni el admin ve la de Ana")

    # --- canales de aviso: lista por usuario, varios tipos, validación y secretos
    r = ana_client.get("/profile/channels/new")
    check("Discord" in r.text and "Telegram" in r.text, "elegir el tipo de canal")
    bad = ana_client.post("/profile/channels", data={"kind": "discord", "name": "x", "webhook": "https://evil.example/hook"})
    check("webhook de Discord no es válida" in bad.text, "validación del webhook de Discord")
    bad = ana_client.post("/profile/channels", data={"kind": "telegram", "token": "x", "chat_id": "hola"})
    check("token del bot" in bad.text and "chat ID" in bad.text, "validación de Telegram")
    check(ana_client.post("/profile/channels", data={"kind": "sms"}).status_code == 400, "tipo de canal desconocido")
    for data in ({"kind": "discord", "name": "Mi Discord", "enabled": "1", "webhook": "https://discord.com/api/webhooks/2/ana"},
                 {"kind": "discord", "name": "Discord del grupo", "enabled": "1", "webhook": "https://discord.com/api/webhooks/3/grupo"},
                 {"kind": "telegram", "name": "Mi Telegram", "enabled": "1", "token": "123456:ABCDEFGHIJKLMNOPQRSTUVWX", "chat_id": "42"}):
        r = ana_client.post("/profile/channels", data=data, follow_redirects=False)
        check(r.status_code == 303, f"Ana añade el canal «{data['name']}»")
    with db.connect() as con:
        chans = {c["name"]: c for c in db.list_channels(con, ana["id"])}
    check(set(chans) == {"Mi Discord", "Discord del grupo", "Mi Telegram"}, "un usuario puede tener varios canales, también del mismo tipo")
    page = ana_client.get("/profile").text
    check("Mi Telegram" in page and "webhooks/2/ana" not in page and "ABCDEFGH" not in page, "la lista de canales no muestra secretos")
    page = ana_client.get(f"/profile/channels/{chans['Mi Discord']['id']}/edit").text
    check("webhooks/2/ana" not in page and "guardado" in page, "ni siquiera al editar vuelve el secreto")
    r = ana_client.post(f"/profile/channels/{chans['Mi Discord']['id']}/edit", data={"name": "Mi Discord", "enabled": "1", "webhook": ""},
                        follow_redirects=False)
    with db.connect() as con:
        check(db.get_channel(con, chans["Mi Discord"]["id"])["config"]["webhook"].endswith("/2/ana"), "secreto vacío = se conserva el guardado")
    check(ana_client.post(f"/profile/channels/{chans['Mi Telegram']['id']}/test", follow_redirects=False).status_code == 303
          and "Mi Telegram" in TARGETS[-1], "mensaje de prueba a un canal")

    # --- asignar canales a cada vigilancia
    ids = {n: c["id"] for n, c in chans.items()}
    with db.connect() as con:
        admin_chan_id = db.list_channels(con, admin_id)[0]["id"]
    form = {"name": "Vigilancia de Ana", "origin": "MAD", "destination": "BCN", "providers": ["mockweb"],
            "max_price": "100", "enabled": "1"}
    check("Mi Discord" in ana_client.get(f"/watches/{ana_watch['id']}/edit").text, "el formulario ofrece los canales del usuario")
    check("Mi Telegram" not in admin_client.get("/watches/new").text, "…y solo los suyos")
    ana_client.post(f"/watches/{ana_watch['id']}/edit", data={**form, "channels": [str(ids["Mi Discord"]), str(admin_chan_id)]},
                    follow_redirects=False)
    with db.connect() as con:
        check(db.get_watch(con, ana_watch["id"])["channel_ids"] == [ids["Mi Discord"]], "un canal ajeno no se puede asignar")
    # el aviso de Ana solo va al canal asignado (no a su Telegram ni al del grupo)
    with db.connect() as con:
        db.set_watch_channels(con, ana_watch["id"], [ids["Mi Discord"]])
    SENT.clear(); TARGETS.clear()
    checker.run_checks(user_id=ana["id"], trigger="manual")
    check(len(SENT) == 1 and TARGETS == [("Mi Discord",)] and "Vigilancia de Ana" in "\n".join(SENT[0][0]),
          "el aviso va solo al canal asignado a la vigilancia")
    with db.connect() as con:  # varios canales a la vez; uno pausado no recibe
        db.set_watch_channels(con, ana_watch["id"], [ids["Mi Discord"], ids["Mi Telegram"], ids["Discord del grupo"]])
        con.execute(text("DELETE FROM alerts WHERE watch_id = :w"), {"w": ana_watch["id"]})
    ana_client.post(f"/profile/channels/{ids['Discord del grupo']}/edit", data={"name": "Discord del grupo", "webhook": ""}, follow_redirects=False)
    SENT.clear(); TARGETS.clear()
    checker.run_checks(user_id=ana["id"], trigger="manual")
    check(TARGETS == [("Mi Discord", "Mi Telegram")], "avisa a todos los canales asignados y activos (el pausado, no)")
    with db.connect() as con:
        con.execute(text("DELETE FROM alerts WHERE watch_id = :w"), {"w": ana_watch["id"]})
        db.set_watch_channels(con, ana_watch["id"], [])
    SENT.clear(); TARGETS.clear()
    checker.run_checks(user_id=ana["id"], trigger="manual")
    check(not SENT, "sin canales asignados no se avisa")
    SENT.clear(); TARGETS.clear()
    checker.run_checks(user_id=admin_id, trigger="manual")
    check(all(t == ("Discord admin",) for t in TARGETS) and not any("Vigilancia de Ana" in "\n".join(m[0]) for m in SENT),
          "las rondas por usuario no mezclan vigilancias ni canales")
    check("Avisa a: Discord admin" in admin_client.get("/").text and "Sin canales de aviso" in ana_client.get("/").text,
          "el panel indica a qué canales avisa cada vigilancia")

    # --- aislamiento de canales entre usuarios
    for path in (f"/profile/channels/{admin_chan_id}/edit",):
        check(ana_client.get(path).status_code == 404, "no se puede abrir un canal ajeno")
    check(ana_client.post(f"/profile/channels/{admin_chan_id}/delete", follow_redirects=False).status_code == 404, "ni borrarlo")
    check(ana_client.post(f"/profile/channels/{admin_chan_id}/test", follow_redirects=False).status_code == 404, "ni probarlo")
    check(ana_client.get(f"/admin/users/{ana['id']}/channels/new").status_code == 403, "las rutas de canales de admin están protegidas")

    # --- el admin gestiona los canales de un usuario
    check("Mi Telegram" in admin_client.get(f"/admin/users/{ana['id']}/edit").text, "el admin ve los canales del usuario (sin secretos)")
    check("ABCDEFGH" not in admin_client.get(f"/admin/users/{ana['id']}/edit").text, "…sin secretos")
    r = admin_client.post(f"/admin/users/{ana['id']}/channels", data={"kind": "discord", "name": "Puesto por el admin", "enabled": "1",
                          "webhook": "https://discord.com/api/webhooks/4/admin-para-ana"}, follow_redirects=False)
    with db.connect() as con:
        made = [c for c in db.list_channels(con, ana["id"]) if c["name"] == "Puesto por el admin"]
    check(r.status_code == 303 and made, "el admin crea un canal para Ana")
    check("Puesto por el admin" in ana_client.get("/profile").text, "Ana lo ve en su perfil")
    r = admin_client.post(f"/admin/users/{ana['id']}/channels/{made[0]['id']}/edit", data={"name": "Renombrado", "enabled": "1", "webhook": ""},
                          follow_redirects=False)
    with db.connect() as con:
        c = db.get_channel(con, made[0]["id"])
    check(c["name"] == "Renombrado" and c["config"]["webhook"].endswith("admin-para-ana"), "el admin edita el canal y conserva el secreto")
    check(admin_client.post(f"/admin/users/{admin_id}/channels/{made[0]['id']}/edit", data={"name": "x"}, follow_redirects=False).status_code == 404,
          "…solo dentro del usuario indicado en la URL")
    check(admin_client.post(f"/admin/users/{ana['id']}/channels/{made[0]['id']}/test", follow_redirects=False).status_code == 303, "el admin prueba el canal")
    admin_client.post(f"/admin/users/{ana['id']}/channels/{made[0]['id']}/delete", follow_redirects=False)
    with db.connect() as con:
        check(db.get_channel(con, made[0]["id"]) is None, "el admin elimina el canal")
    ana_client.post(f"/profile/channels/{ids['Mi Discord']}/delete", follow_redirects=False)
    with db.connect() as con:
        db.set_watch_channels(con, ana_watch["id"], [ids["Mi Telegram"]])
    check(ana_client.post(f"/profile/channels/{ids['Mi Telegram']}/delete", follow_redirects=False).status_code == 303, "Ana borra un canal")
    with db.connect() as con:
        check(db.get_watch(con, ana_watch["id"])["channel_ids"] == [], "borrar un canal lo quita de las vigilancias que lo usaban")
    ana_client.post("/profile", data={"display_name": "Ana G.", "notify_errors": "1"}, follow_redirects=False)

    # --- contraseña propia: las demás sesiones se cierran
    other_session = TestClient(app)
    login(other_session, "ana", "clave-de-ana-1")
    bad = ana_client.post("/profile/password", data={"current_password": "mal", "new_password": "nueva-clave-9", "confirm_password": "otra"})
    check("actual no es correcta" in bad.text and "no coincide" in bad.text, "validación del cambio de contraseña")
    r = ana_client.post("/profile/password", data={"current_password": "clave-de-ana-1", "new_password": "nueva-clave-9",
                                                   "confirm_password": "nueva-clave-9"}, follow_redirects=False)
    check(r.status_code == 303 and ana_client.get("/").status_code == 200, "la sesión que cambia la clave sigue activa")
    check(other_session.get("/", follow_redirects=False).status_code == 303, "las demás sesiones se cierran al cambiar la clave")
    check(login(TestClient(app), "ana", "clave-de-ana-1").status_code == 200, "la clave vieja ya no vale")

    # --- reglas de seguridad del CRUD
    r = admin_client.post(f"/admin/users/{admin_id}/delete", follow_redirects=False)
    check("propia" in unquote(r.headers["location"]), "el admin no puede borrarse a sí mismo")
    r = admin_client.post(f"/admin/users/{admin_id}/edit", data={"username": "admin", "role": "user"}, follow_redirects=False)
    with db.connect() as con:
        check(db.get_user(con, admin_id)["role"] == "admin" and db.get_user(con, admin_id)["enabled"], "el admin no puede quitarse el rol ni desactivarse")
    r = admin_client.post(f"/admin/users/{ana['id']}/edit", data={"username": "ana", "display_name": "Ana", "role": "admin",
                                                                  "enabled": "1"}, follow_redirects=False)
    check(r.status_code == 303 and ana_client.get("/admin/users").status_code == 200, "ascender a admin")
    r = ana_client.post(f"/admin/users/{admin_id}/edit", data={"username": "admin", "role": "user", "enabled": "1"},
                        follow_redirects=False)
    with db.connect() as con:
        check(db.get_user(con, admin_id)["role"] == "user" and db.count_admins(con) == 1, "otro admin puede cambiar el rol")
    old_admin = TestClient(app)
    login(old_admin, "admin", "clave-de-prueba-1")
    check(old_admin.get("/admin/users").status_code == 403, "el degradado ya no es admin")
    ana_client.post(f"/admin/users/{ana['id']}/edit", data={"username": "ana", "role": "user"}, follow_redirects=False)
    with db.connect() as con:
        check(db.get_user(con, ana["id"])["role"] == "admin" and db.get_user(con, ana["id"])["enabled"],
              "nadie puede degradarse o desactivarse a sí mismo (queda siempre un admin)")
    ana_client.post(f"/admin/users/{admin_id}/edit", data={"username": "admin", "role": "admin", "enabled": "1"},
                    follow_redirects=False)

    # --- desactivar: pierde la sesión y sus vigilancias dejan de comprobarse
    r = admin_client.post(f"/admin/users/{ana['id']}/edit", data={"username": "ana", "role": "user"}, follow_redirects=False)
    check(ana_client.get("/", follow_redirects=False).status_code == 303, "usuario desactivado: sesión cerrada")
    check(login(TestClient(app), "ana", "nueva-clave-9").status_code == 200, "usuario desactivado: no puede entrar")
    check(checker.run_checks(user_id=ana["id"], trigger="manual") == "empty", "sus vigilancias no se comprueban")

    # --- eliminar usuario: se lleva sus vigilancias y su avatar
    avatar_path = config.AVATAR_DIR / ana["avatar"]
    check(avatar_path.exists(), "el archivo del avatar existe")
    r = admin_client.post(f"/admin/users/{ana['id']}/delete", follow_redirects=False)
    with db.connect() as con:
        check(db.get_user(con, ana["id"]) is None and db.get_watch(con, ana_watch["id"]) is None, "se borra el usuario y sus vigilancias")
        n = con.execute(text("SELECT count(*) FROM prices WHERE watch_id = :w"), {"w": ana_watch["id"]}).scalar()
    check(n == 0 and not avatar_path.exists(), "…con su histórico y su avatar")
    r = admin_client.post("/logout", follow_redirects=False)
    check(r.status_code == 303 and admin_client.get("/", follow_redirects=False).status_code == 303, "cerrar sesión")
    check(login(admin_client, "admin", "clave-de-prueba-1").status_code == 303, "volver a entrar")


def main():
    with TestClient(app) as client:
        # --- sesión: sin login no hay acceso
        r = client.get("/", follow_redirects=False)
        check(r.status_code == 303 and r.headers["location"] == "/login", "sin sesión → redirige a /login")
        check(client.get("/api/status").status_code == 401, "la API responde 401 sin sesión")
        check(client.get("/login").status_code == 200, "GET /login")
        check("incorrectos" in login(client, "admin", "mala").text, "contraseña incorrecta rechazada")
        check(login(client, "nadie", "x").status_code == 200, "usuario inexistente rechazado")
        for _ in range(5):
            login(client, "bloqueado", "x")
        check("Demasiados intentos" in login(client, "bloqueado", "x").text, "freno tras varios intentos fallidos")
        r = client.post("/login", data={"username": "Admin", "password": "clave-de-prueba-1", "next": "//evil.example"},
                        follow_redirects=False)
        check(r.status_code == 303 and r.headers["location"] == "/", "login válido (usuario sin distinguir mayúsculas) y next externo ignorado")
        with db.connect() as con:
            admin_id = db.get_user_by_username(con, "admin")["id"]
            admin_row = db.get_user(con, admin_id)
        check(admin_row["role"] == "admin" and admin_row["password_hash"].startswith("scrypt$"), "administrador inicial con hash scrypt")

        # --- páginas base
        for path in ("/", "/watches/new", "/settings", "/runs", "/debug"):
            check(client.get(path).status_code == 200, f"GET {path}")
        check("Sevilla → Tenerife" in client.get("/").text and "SVQ → TCI" in client.get("/").text,
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
        runs = client.get("/runs").text
        check("La web no devolvió" not in runs, "una ruta no operada dentro de TCI no cuenta como error")

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

        # --- panel, detalle y gráficas
        page = client.get(f"/watches/{wid}")
        check(page.status_code == 200 and "chart-min" in page.text, "detalle con gráficas")
        day = (TODAY + timedelta(days=11)).isoformat()  # el más barato de la ronda simulada
        check('class="cal"' in page.text and f'data-date="{day}"' in page.text, "detalle con calendario de precios")
        check(re.search(r'/static/style\.css\?v=[0-9a-f]{10}"', page.text), "el CSS lleva huella de versión")
        charts = client.get(f"/api/watches/{wid}/charts").json()
        check(charts["min_over_time"]["labels"] and "mockweb" in charts["min_over_time"]["series"], "API de gráficas")
        hist = client.get(f"/api/watches/{wid}/date-history", params={"date": (TODAY + timedelta(days=20)).isoformat()}).json()
        check(len(hist["labels"]) >= 1, "API del historial de una fecha")
        check(client.get("/watches/1?provider=vueling").status_code == 200, "filtro por proveedor")
        home = client.get("/").text
        check("tickets.vueling.com/booking" in home and "d=TFN" in home, "el panel muestra el enlace con fecha y aeropuerto real")
        check("originIata=SVQ&amp;destinationIata=TFS" in home and "SVQ→TFS" in home, "Ryanair enlaza a TFS dentro de TCI")

        # --- ajustes: plantilla de enlace personalizada y validaciones
        r = client.post("/settings", data={
            "schedule_hours": "8,20", "schedule_minute": "30", "timezone": "Europe/Madrid", "max_months": "11",
            "min_samples": "30", "retention_days": "400", "headless": "1", "notify_errors": "1",
            "link_ryanair": "https://www.ryanair.com/x?o={origin}&d={destination}&f={date_dmy}", "link_vueling": "",
        }, follow_redirects=False)
        check(r.status_code == 303, "guardar ajustes")
        s = db.get_settings()
        check(s["schedule_hours"] == "8,20", "ajustes persistidos")
        with db.connect() as con:
            check(len(db.list_channels(con, admin_id)) == 1, "los ajustes no tocan los canales del usuario")
        bad = client.post("/settings", data={"schedule_hours": "99", "schedule_minute": "0", "timezone": "Nope/Zone",
                                             "max_months": "11", "min_samples": "30", "retention_days": "400"})
        check("Las horas deben ser" in bad.text and "Zona horaria desconocida" in bad.text, "validación de ajustes")
        link = PROVIDERS["ryanair"].build_link(s["link_ryanair"], "SVQ", "TFN", date(2026, 10, 24))
        check(link.endswith("f=24/10/2026"), "plantilla de enlace personalizada")

        # --- CRUD de vigilancias
        bad = client.post("/watches", data={"origin": "SV", "destination": "TFN"})
        check("código IATA" in bad.text and "al menos un proveedor" in bad.text, "validación del formulario")
        r = client.post("/watches", data={"origin": "agp", "destination": "bcn", "providers": ["vueling"], "max_price": "25"},
                        follow_redirects=False)
        check(r.status_code == 303, "crear vigilancia")
        with db.connect() as con:
            new = [w for w in db.list_watches(con) if w["origin"] == "AGP"][0]
        check(new["destination"] == "BCN" and new["max_price"] == 25.0, "IATA normalizado a mayúsculas")
        check(client.post(f"/watches/{new['id']}/toggle", follow_redirects=False).status_code == 303, "pausar/reanudar")
        check(client.post(f"/watches/{new['id']}/delete", follow_redirects=False).status_code == 303, "eliminar")
        check(client.get("/api/status").json() == {"running": False, "current": ""}, "estado de ejecución")
        check(client.get("/runs").text.count("correcta") >= 2, "historial de ejecuciones")

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
