"""Validação, normalização e máscara de CPF (formato + dígitos verificadores)."""
import re

_FORMAT = re.compile(r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$")

MSG_FORMAT = "Informe o CPF no formato 000.000.000-00 (11 dígitos)."
MSG_INVALID = "CPF inválido: os dígitos verificadores não conferem."


def _check_digit(digits: str) -> int:
    """Dígito verificador: pesos decrescentes de len+1 até 2, módulo 11."""
    total = sum(int(d) * w for d, w in zip(digits, range(len(digits) + 1, 1, -1)))
    rest = (total * 10) % 11
    return 0 if rest == 10 else rest


def normalize_cpf(value) -> str | None:
    """Retorna os 11 dígitos se o *formato* for aceito; senão None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not _FORMAT.match(value):
        return None
    return re.sub(r"\D", "", value)


def is_valid_cpf(value) -> bool:
    digits = normalize_cpf(value)
    if not digits or digits == digits[0] * 11:  # 111.111.111-11 etc. passam na conta, mas são inválidos
        return False
    return int(digits[9]) == _check_digit(digits[:9]) and int(digits[10]) == _check_digit(digits[:10])


def validate_cpf(value) -> tuple[str | None, str | None]:
    """(dígitos, None) se válido; (None, mensagem de erro) caso contrário."""
    digits = normalize_cpf(value)
    if digits is None:
        return None, MSG_FORMAT
    if not is_valid_cpf(digits):
        return None, MSG_INVALID
    return digits, None


def format_cpf(digits: str) -> str:
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def mask_cpf(value: str) -> str:
    """Máscara LGPD: ***.456.789-** (oculta os 3 primeiros e os 2 últimos dígitos)."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 11:
        raise ValueError("CPF deve ter 11 dígitos")
    return f"***.{digits[3:6]}.{digits[6:9]}-**"
