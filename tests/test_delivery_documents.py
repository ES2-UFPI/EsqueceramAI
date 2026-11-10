import io

import pytest
from werkzeug.datastructures import FileStorage

from app.delivery.documents import MAX_BYTES, sniff_mime, validate_document
from app.delivery.security import sha256_hex
from app.errors import ApiError

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 64


def f(data, name="doc.jpg", mime="image/jpeg"):
    return FileStorage(stream=io.BytesIO(data), filename=name, content_type=mime)


@pytest.mark.parametrize("data,mime", [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")])
def test_accepts_real_images_and_hashes(data, mime):
    doc = validate_document(f(data))
    assert doc.mime_type == mime and doc.size_bytes == len(data) and doc.sha256 == sha256_hex(data)


def test_content_type_is_ignored_signature_wins():
    assert validate_document(f(PNG, "x.jpg", "image/jpeg")).mime_type == "image/png"
    with pytest.raises(ApiError):  # ficou claro: declarar image/png não basta
        validate_document(f(b"<script>alert(1)</script>" * 3, "x.png", "image/png"))


@pytest.mark.parametrize("bad", [None, f(b"", "")])
def test_missing_file(bad):
    with pytest.raises(ApiError) as e:
        validate_document(bad)
    assert e.value.status == 422 and "document" in e.value.details


def test_rejects_empty_pdf_gif_and_oversize():
    for data, name in [(b"", "a.jpg"), (b"%PDF-1.4" + b"0" * 50, "a.pdf"), (b"GIF89a" + b"0" * 50, "a.gif")]:
        with pytest.raises(ApiError):
            validate_document(f(data, name))
    with pytest.raises(ApiError) as e:
        validate_document(f(JPEG + b"0" * MAX_BYTES))
    assert "5 MB" in e.value.message


def test_sniff():
    assert sniff_mime(b"abc") is None
