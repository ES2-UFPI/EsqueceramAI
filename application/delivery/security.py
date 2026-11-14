"""Código de confirmação e hashes com HMAC.

Chave: DELIVERY_HMAC_KEY (ou SECRET_KEY). Em produção defina uma chave forte e estável: se ela mudar,
os códigos pendentes e as conferências de CPF de entregas antigas deixam de funcionar.
"""
import hashlib
import hmac
import os
import secrets

CODE_DIGITS = 6
CODE_TTL_MINUTES = 15
MAX_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60
MAX_RESENDS = 3


def _key() -> bytes:
    return (os.getenv("DELIVERY_HMAC_KEY") or os.getenv("SECRET_KEY") or "dev-secret").encode()


def _mac(message: str) -> str:
    return hmac.new(_key(), message.encode(), hashlib.sha256).hexdigest()


def generate_code() -> str:
    """Código numérico de 6 dígitos criptograficamente aleatório."""
    return f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"


def hash_code(delivery_id: int, code: str) -> str:
    return _mac(f"code:{delivery_id}:{code}")


def verify_code(delivery_id: int, code: str, stored_hash: str | None) -> bool:
    if not stored_hash or not isinstance(code, str):
        return False
    return hmac.compare_digest(hash_code(delivery_id, code.strip()), stored_hash)


def hash_cpf(cpf_digits: str) -> str:
    """HMAC do CPF: permite conferir um CPF apresentado numa contestação sem guardá-lo em claro."""
    return _mac(f"cpf:{cpf_digits}")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def mac_hex(message: str) -> str:
    """HMAC genérico (usado no código de verificação do recibo)."""
    return _mac(message)
