"""Imagem do documento com foto do retirante (upload de arquivo ou captura pela câmera).

Valida o conteúdo real (assinatura do arquivo) e não só o Content-Type enviado pelo navegador.
"""
from dataclasses import dataclass

from app.delivery.security import sha256_hex
from app.errors import ApiError

MAX_BYTES = 5 * 1024 * 1024
ALLOWED = ("image/jpeg", "image/png", "image/webp")
MIN_BYTES = 10  # descarta arquivos vazios/truncados


@dataclass(frozen=True)
class DocumentImage:
    data: bytes
    mime_type: str
    size_bytes: int
    sha256: str


def sniff_mime(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _fail(message: str):
    raise ApiError(message, 422, {"document": [message]})


def validate_document(file) -> DocumentImage:
    """`file` é um werkzeug FileStorage (campo `document`). Levanta ApiError 422 se inválido."""
    if file is None or not getattr(file, "filename", ""):
        _fail("Anexe ou capture a foto do documento do retirante.")
    data = file.read()
    if len(data) < MIN_BYTES:
        _fail("O arquivo do documento está vazio.")
    if len(data) > MAX_BYTES:
        _fail("A imagem do documento deve ter no máximo 5 MB.")
    mime = sniff_mime(data)
    if mime not in ALLOWED:
        _fail("Envie uma imagem JPG, PNG ou WebP do documento.")
    return DocumentImage(data=data, mime_type=mime, size_bytes=len(data), sha256=sha256_hex(data))
