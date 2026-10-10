"""Perfil propio (datos, avatar, contraseña) y canales de aviso (los propios o, el admin, los de cualquiera)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from .. import auth, avatars, db, notify
from .deps import Invalid, channel_rows, current_user, require_admin
from .session import me_view

router = APIRouter()


# ------------------------------------------------------------------------ avatar
def read_upload(upload: UploadFile | None) -> bytes:
    if upload is None or not upload.filename:
        raise Invalid("No se ha recibido ninguna imagen.")
    return upload.file.read(avatars.MAX_BYTES + 1)


def replace_avatar(con, user: dict, data: bytes) -> str:
    """Guarda la nueva imagen, borra la anterior y devuelve el nombre. `Invalid` si no es una imagen válida."""
    try:
        name = avatars.save(user["id"], data)
    except ValueError as exc:
        raise Invalid(str(exc)) from exc
    avatars.remove(user["avatar"])
    db.update_user(con, user["id"], avatar=name)
    return name


def drop_avatar(con, user: dict):
    if user["avatar"]:
        avatars.remove(user["avatar"])
        db.update_user(con, user["id"], avatar=None)


# ------------------------------------------------------------------------ perfil
class ProfileIn(BaseModel):
    display_name: str = ""
    notify_errors: bool = True


class PasswordIn(BaseModel):
    current_password: str = ""
    new_password: str = ""
    confirm_password: str = ""


def _fresh(uid: int) -> dict:
    with db.connect() as con:
        return me_view(db.get_user(con, uid))


@router.put("/profile")
def save_profile(body: ProfileIn, user: dict = Depends(current_user)):
    with db.connect() as con:
        db.update_user(con, user["id"], display_name=body.display_name.strip()[:100] or user["display_name"],
                       notify_errors=body.notify_errors)
    return {"user": _fresh(user["id"])}


@router.post("/profile/avatar")
def upload_profile_avatar(avatar: UploadFile | None = File(None), user: dict = Depends(current_user)):
    data = read_upload(avatar)
    with db.connect() as con:
        replace_avatar(con, user, data)
    return {"user": _fresh(user["id"])}


@router.delete("/profile/avatar")
def delete_profile_avatar(user: dict = Depends(current_user)):
    with db.connect() as con:
        drop_avatar(con, user)
    return {"user": _fresh(user["id"])}


@router.post("/profile/password")
def change_password(body: PasswordIn, request: Request, user: dict = Depends(current_user)):
    errors = []
    if not auth.verify_password(body.current_password, user["password_hash"]):
        errors.append("La contraseña actual no es correcta.")
    if err := auth.validate_password(body.new_password):
        errors.append(err)
    if body.new_password != body.confirm_password:
        errors.append("La confirmación no coincide con la nueva contraseña.")
    if errors:
        raise Invalid(errors)
    new_hash = auth.hash_password(body.new_password)
    with db.connect() as con:
        db.update_user(con, user["id"], password_hash=new_hash)
    request.session["ph"] = auth.fingerprint(new_hash)  # esta sesión sigue; las demás se cierran
    return {"ok": True}


# ------------------------------------------------- canales de aviso (propios o, el admin, de cualquiera)
class ChannelIn(BaseModel):
    kind: str = ""
    name: str = ""
    enabled: bool = True
    config: dict[str, str] = {}


def owner_self(user: dict = Depends(current_user)) -> dict:
    return user


def owner_admin(uid: int, admin: dict = Depends(require_admin)) -> dict:
    with db.connect() as con:
        owner = db.get_user(con, uid)
    if not owner:
        raise HTTPException(404, "No existe ese usuario")
    return owner


def _channel_routes(prefix: str, owner_dep):
    """Mismas rutas para `/channels…` (el propio usuario) y `/users/{uid}/channels…` (admin)."""

    def own_channel(con, owner: dict, cid: int) -> dict:
        ch = db.get_channel(con, cid)
        if not ch or ch["user_id"] != owner["id"] or ch["kind"] not in notify.KINDS:
            raise HTTPException(404, "No existe ese canal")
        return ch

    def detail(ch: dict) -> dict:
        return {**channel_rows([ch])[0], "fields": notify.view_fields(ch["kind"], ch["config"])}

    def clean_name(body: ChannelIn, kind: str) -> str:
        return body.name.strip()[:100] or notify.KINDS[kind]["label"]

    @router.get(prefix + "/channels")
    def list_channels(owner: dict = Depends(owner_dep)):
        with db.connect() as con:
            return {"channels": channel_rows(db.list_channels(con, owner["id"]))}

    @router.post(prefix + "/channels", status_code=201)
    def create_channel(body: ChannelIn, owner: dict = Depends(owner_dep)):
        if body.kind not in notify.KINDS:
            raise Invalid("Tipo de canal desconocido.", status=400)
        config, errors = notify.validate_config(body.kind, body.config)
        if errors:
            raise Invalid(errors)
        with db.connect() as con:
            cid = db.create_channel(con, owner["id"], body.kind, clean_name(body, body.kind), config, body.enabled)
            return {"channel": detail(db.get_channel(con, cid))}

    @router.get(prefix + "/channels/{cid}")
    def get_channel(cid: int, owner: dict = Depends(owner_dep)):
        with db.connect() as con:
            return {"channel": detail(own_channel(con, owner, cid))}

    @router.put(prefix + "/channels/{cid}")
    def update_channel(cid: int, body: ChannelIn, owner: dict = Depends(owner_dep)):
        with db.connect() as con:
            ch = own_channel(con, owner, cid)
            config, errors = notify.validate_config(ch["kind"], body.config, ch["config"])
            if errors:
                raise Invalid(errors)
            db.update_channel(con, cid, clean_name(body, ch["kind"]), config, body.enabled)
            return {"channel": detail(db.get_channel(con, cid))}

    @router.delete(prefix + "/channels/{cid}", status_code=204)
    def delete_channel(cid: int, owner: dict = Depends(owner_dep)):
        with db.connect() as con:
            own_channel(con, owner, cid)
            db.delete_channel(con, cid)
        return Response(status_code=204)

    @router.post(prefix + "/channels/{cid}/test")
    def test_channel(cid: int, owner: dict = Depends(owner_dep)):
        with db.connect() as con:
            ch = own_channel(con, owner, cid)
        _ok, errors = notify.send_text([ch], "✅ Flight Watcher: las notificaciones funcionan.")
        if errors:
            raise Invalid("Fallo al enviar: " + ", ".join(errors), status=502)
        return {"ok": True}


_channel_routes("", owner_self)
_channel_routes("/users/{uid}", owner_admin)
