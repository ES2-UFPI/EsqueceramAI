import io
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from pypdf import PdfReader

from application.delivery.cpf import mask_cpf
from application.delivery.receipt import (ReceiptData, build_receipt_pdf, format_local, receipt_number, verification_code)
from application.delivery.security import hash_cpf, sha256_hex

CPF = "52998224725"
CONFIRMED = datetime(2026, 11, 8, 17, 32, 10, tzinfo=timezone.utc)   # 14:32:10 em Fortaleza


@pytest.fixture()
def data():
    return ReceiptData(delivery_id=12, created_at=CONFIRMED, confirmed_at=CONFIRMED, item_code="ESQ-00019",
                       item_title="Mochila cinza com chaveiro", point_name="Administração Central",
                       recipient_name="Maria de Sousa Lima", cpf_masked=mask_cpf(CPF), cpf_hash=hash_cpf(CPF),
                       email_masked="m***@gmail.com", attendant_name="Renata Nunes",
                       attendant_registration="ATD-2024-0117", document_sha256=sha256_hex(b"foto"))


def text_of(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


def test_pdf_has_required_content(data):
    pdf, code = build_receipt_pdf(data)
    assert pdf.startswith(b"%PDF")
    t = text_of(pdf)
    assert "ESQ-00019" in t                                   # identificador do item
    assert "***.982.247-**" in t                              # CPF mascarado
    assert "ATD-2024-0117" in t and "Renata Nunes" in t       # matrícula e atendente
    assert "08/11/2026 14:32:10" in t and "2026-11-08T17:32:10Z" in t   # carimbo de data/hora
    assert "ENT-2026-000012" in t and code in t
    assert data.document_sha256 in t.replace("\n", "")


def test_full_cpf_never_printed(data):
    t = text_of(build_receipt_pdf(data)[0]).replace(" ", "").replace("\n", "")
    for form in (CPF, "529.982.247-25", "52998224725"):
        assert form not in t
    assert data.cpf_hash not in t                            # o hash também não é impresso


def test_verification_code_is_tamper_evident(data):
    base = verification_code(data)
    assert len(base) == 23 and base == verification_code(data)
    assert verification_code(replace(data, item_code="ESQ-00020")) != base
    assert verification_code(replace(data, attendant_registration="OUTRA")) != base
    assert verification_code(replace(data, cpf_hash=hash_cpf("39053344705"))) != base
    assert verification_code(replace(data, document_sha256=sha256_hex(b"outra"))) != base


def test_handles_accents_and_markup(data):
    pdf, _ = build_receipt_pdf(replace(data, recipient_name="José Antônio <b>& Filhos</b>", item_title="Calça & Cinto"))
    t = text_of(pdf)
    assert "José Antônio" in t and "Calça & Cinto" in t


def test_number_and_local_time():
    assert receipt_number(7, CONFIRMED) == "ENT-2026-000007"
    assert format_local(CONFIRMED).startswith("08/11/2026 14:32:10")
