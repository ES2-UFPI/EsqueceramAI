import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

os.environ["FRONTEND_ORIGIN"] = "http://localhost:5500"

from app import app


def test_health():
    response = app.test_client().get("/api/health")

    assert response.status_code == 200
    assert response.json == {"status": "healthy"}
