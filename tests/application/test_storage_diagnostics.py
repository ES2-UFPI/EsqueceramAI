import io
import json
import urllib.error

from application.services import storage_service
from conftest import persona_client


class _Resp:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._raw


def test_diagnose_reports_missing_credentials(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    result = storage_service.diagnose_bucket()
    assert result["provider"] == "DATABASE"
    assert result["urlConfigured"] is False and result["keyConfigured"] is False
    assert "error" in result


def test_diagnose_reports_bucket_metadata(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_muito_secreto")
    monkeypatch.setattr(storage_service.urllib.request, "urlopen",
                        lambda *_a, **_kw: _Resp({"public": False, "file_size_limit": 3145728}))
    result = storage_service.diagnose_bucket()
    assert result["provider"] == "SUPABASE" and result["bucketExists"] is True
    assert result["isPublic"] is False
    assert "sb_secret_muito_secreto" not in json.dumps(result)


def test_diagnose_reports_missing_bucket_on_404(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_x")

    def not_found(req, timeout=10):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {},
                                     io.BytesIO(b'{"message":"Bucket not found"}'))

    monkeypatch.setattr(storage_service.urllib.request, "urlopen", not_found)
    result = storage_service.diagnose_bucket()
    assert result["bucketExists"] is False and result["httpStatus"] == 404


def test_scrub_hides_credentials():
    text = storage_service._scrub("falhou key=abc123&alt=1 e token sb_secret_zzz", "sb_secret_zzz")
    assert "sb_secret_zzz" not in text and "abc123" not in text


def test_upload_error_surfaces_http_code_without_leaking_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_chave")
    captured = {}

    def denied(req, timeout=15):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {},
                                     io.BytesIO(b'{"message":"new row violates policy","key":"sb_secret_chave"}'))

    monkeypatch.setattr(storage_service.urllib.request, "urlopen", denied)
    monkeypatch.setattr(storage_service.log, "warning",
                        lambda msg, *a, **kw: captured.update(args=a))

    class _File:
        filename, mimetype = "foto.png", "image/png"

        def read(self):
            return b"\x89PNG" + b"0" * 32

    try:
        storage_service.store_item_image(1, _File())
    except storage_service.ApiError as exc:
        assert exc.status == 502 and "403" in exc.message
    else:
        raise AssertionError("deveria falhar")
    logged = " ".join(str(a) for a in captured.get("args", ()))
    assert "sb_secret_chave" not in logged and "403" in logged


def test_storage_diagnostic_requires_admin(app, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_x")
    monkeypatch.setattr(storage_service.urllib.request, "urlopen",
                        lambda *_a, **_kw: _Resp({"public": False}))
    assert persona_client(app, "carlos@ufpi.edu.br").get("/api/health/storage").status_code == 403
    admin = persona_client(app, "admin@ufpi.edu.br")
    res = admin.get("/api/health/storage")
    assert res.status_code == 200 and res.get_json()["bucket"] == "item-images"
