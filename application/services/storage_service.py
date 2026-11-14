"""Armazenamento privado de imagens (src/server/services/storage-service.ts).

Com SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY usa o bucket privado `item-images`
(URLs assinadas de 5 min). Sem credenciais, o mesmo contrato é atendido pelo banco.
"""
import json
import os
import urllib.error
import urllib.request
import uuid

from application.errors import ApiError
from application.repositories.items import find_item_image, save_item_image

BUCKET = "item-images"
MAX_BYTES = 3 * 1024 * 1024
ALLOWED = ("image/jpeg", "image/png", "image/webp")


def _creds():
    return (os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


def storage_provider() -> str:
    url, key = _creds()
    return "SUPABASE" if url and key else "DATABASE"


def validate_image(mime: str, size: int):
    if mime not in ALLOWED:
        raise ApiError("Envie uma imagem JPG, PNG ou WebP.", 422, {"image": ["Formato não suportado."]})
    if size > MAX_BYTES:
        raise ApiError("A imagem deve ter no máximo 3 MB.", 422, {"image": ["Arquivo muito grande."]})


def store_item_image(item_id: int, file):
    """`file` é um werkzeug FileStorage."""
    data = file.read()
    mime = file.mimetype or ""
    validate_image(mime, len(data))
    ext = (file.filename.rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "jpg")
    key = f"items/{item_id}/{uuid.uuid4()}.{ext}"
    url, svc_key = _creds()

    if storage_provider() == "SUPABASE":
        req = urllib.request.Request(
            f"{url}/storage/v1/object/{BUCKET}/{key}", data=data, method="POST",
            headers={"Authorization": f"Bearer {svc_key}", "Content-Type": mime, "x-upsert": "true"})
        try:
            urllib.request.urlopen(req, timeout=15).close()
        except (urllib.error.URLError, OSError):
            raise ApiError("Falha ao enviar a imagem para o armazenamento privado.", 502)
        save_item_image(item_id=item_id, provider="SUPABASE", storage_key=key, mime_type=mime,
                        size_bytes=len(data), data=None)
        return {"provider": "SUPABASE", "storageKey": key}

    save_item_image(item_id=item_id, provider="DATABASE", storage_key=key, mime_type=mime,
                    size_bytes=len(data), data=data)
    return {"provider": "DATABASE", "storageKey": key}


def resolve_item_image(item_id: int):
    """Retorna ('bytes', mime, data) | ('redirect', url) | None."""
    image = find_item_image(item_id)
    if not image:
        return None
    if image.provider == "DATABASE" and image.data:
        return ("bytes", image.mime_type, bytes(image.data))
    url, svc_key = _creds()
    if url and svc_key and image.provider == "SUPABASE":
        req = urllib.request.Request(
            f"{url}/storage/v1/object/sign/{BUCKET}/{image.storage_key}", data=json.dumps({"expiresIn": 300}).encode(),
            method="POST", headers={"Authorization": f"Bearer {svc_key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                signed = json.loads(resp.read()).get("signedURL")
            if signed:
                return ("redirect", f"{url}/storage/v1{signed}")
        except (urllib.error.URLError, OSError, ValueError):
            pass
    return None
