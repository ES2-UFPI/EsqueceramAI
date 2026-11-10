"""Pequeno validador (substitui o Zod). Acumula erros por campo e levanta ValidationFailed."""
import re
from datetime import datetime

from application.errors import ValidationFailed

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Form:
    def __init__(self, raw: dict | None):
        self.raw = raw or {}
        self.errors: dict[str, list[str]] = {}
        self.data: dict = {}

    def _err(self, key, msg):
        self.errors.setdefault(key, []).append(msg)

    def _val(self, key):
        v = self.raw.get(key)
        return v if v is not None else ""

    def text(self, key, *, min=0, max=None, min_msg=None, max_msg=None, lower=False, required_msg=None, optional=False):
        v = self._val(key)
        v = v.strip() if isinstance(v, str) else (str(v) if v != "" else "")
        if lower:
            v = v.lower()
        if optional and not v:
            self.data[key] = ""
            return v
        if len(v) < min:
            self._err(key, min_msg or required_msg or "Campo obrigatório.")
        elif max is not None and len(v) > max:
            self._err(key, max_msg or "Texto muito longo.")
        self.data[key] = v
        return v

    def raw_text(self, key, *, min=0, max=None, min_msg=None, max_msg=None):
        """Texto sem trim (senhas)."""
        v = self._val(key)
        v = v if isinstance(v, str) else str(v)
        if len(v) < min:
            self._err(key, min_msg or "Campo obrigatório.")
        elif max is not None and len(v) > max:
            self._err(key, max_msg or "Texto muito longo.")
        self.data[key] = v
        return v

    def email(self, key, msg="Informe um e-mail válido."):
        v = self.text(key, lower=True, min=0)
        if not _EMAIL.match(v):
            self._err(key, msg)
        return v

    def choice(self, key, allowed, msg):
        v = self._val(key)
        if v not in allowed:
            self._err(key, msg)
        self.data[key] = v
        return v

    def number(self, key, *, lo=None, hi=None, integer=False, positive=False):
        v = self._val(key)
        if v in ("", None):
            self.data[key] = None
            return None
        try:
            n = float(v)
            if integer and n != int(n):
                raise ValueError
            n = int(n) if integer else n
            if (lo is not None and n < lo) or (hi is not None and n > hi) or (positive and n <= 0):
                raise ValueError
        except (TypeError, ValueError):
            self._err(key, "Valor inválido.")
            n = None
        self.data[key] = n
        return n

    def finish(self) -> dict:
        if self.errors:
            raise ValidationFailed(self.errors)
        return self.data


def parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
