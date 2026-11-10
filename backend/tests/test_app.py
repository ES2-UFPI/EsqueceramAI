"""Smoke tests do contrato de implantação do backend."""
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app  # noqa: E402


def test_health_check_is_available():
    response = app.test_client().get("/api/health")

    assert response.status_code == 200
    assert response.json["status"] == "healthy"
