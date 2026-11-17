import json
import logging
import os
import re
import urllib.error
import urllib.request
import uuid

from application.errors import ApiError
from application.repositories.items import find_item_image, save_item_image

log = logging.getLogger("esqueceram.storage")

BUCKET = "item-images"
MAX_BYTES = 3 * 1024 * 1024
ALLOWED = ("image/jpeg", "image/png", "image/webp")


def _creds():
    return (os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


def storage_provider() -> str:
    url, key = _creds()
    return "SUPABASE" if url and key else "DATABASE"


def _scrub(text: str, *secrets: str) -> str:
    """Remove credenciais de mensagens antes de irem para o log."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return re.sub(r"(key|token|authorization)=([^&\s\"']+)", r"\1=***", text, flags=re.I)


def diagnose_bucket() -> dict:
    """Estado observável do armazenamento, sem enviar arquivos."""
    url, key = _creds()
    result = {
        "provider": storage_provider(),
        "bucket": BUCKET,
        "urlConfigured": bool(url),
        "keyConfigured": bool(key),
        "keyPrefix": (key or "")[:9] or None,
    }
    if not (url and key):
        result["error"] = "SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY precisam estar definidos."
        return result
    try:
        req = urllib.request.Request(f"{url}/storage/v1/bucket/{BUCKET}",
                                     headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        result.update(bucketExists=True, isPublic=info.get("public"),
                      fileSizeLimit=info.get("file_size_limit"),
                      allowedMimes=info.get("allowed_mime_types"))
    except urllib.error.HTTPError as exc:
        body = _scrub(exc.read().decode("utf-8", errors="ignore")[:200], key)
        result.update(bucketExists=exc.code != 404, httpStatus=exc.code, error=body or str(exc))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        result.update(bucketExists=None, error=_scrub(str(getattr(exc, "reason", exc)), key))
    return result


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
        except urllib.error.HTTPError as exc:
            detail = _scrub(exc.read().decode("utf-8", errors="ignore")[:300], svc_key)
            log.warning("Falha no upload ao bucket %s (HTTP %s): %s", BUCKET, exc.code, detail or exc)
            raise ApiError(f"Falha ao enviar a imagem para o armazenamento privado (HTTP {exc.code}).", 502)
        except (urllib.error.URLError, OSError) as exc:
            reason = _scrub(str(getattr(exc, "reason", exc)), svc_key)
            log.warning("Falha no upload ao bucket %s: %s", BUCKET, reason)
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
