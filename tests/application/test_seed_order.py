"""Seed em banco vazio: a ordem de entrada (login demo, cadastro real, home) não pode perder/poluir dados."""
import os
import subprocess
import sys
import tempfile

SCRIPT = """
import sys
from application import create_app
from application.models import db
from application.services import seed_service as s
from application.repositories.items import count_items
from application.repositories.points import count_points
from application.repositories.users import count_users
app = create_app()
scenario = sys.argv[1]
with app.app_context():
    if scenario == "demo_first":
        s.ensure_demo_accounts(); s.ensure_seeded()
    elif scenario == "home_first":
        s.ensure_seeded()
    elif scenario == "real_user_first":
        from application.auth import hash_password
        from application.repositories.users import create_user
        create_user(name="Usuário Real", email="real@empresa.com", password_hash=hash_password("senha-12345"))
        s.ensure_demo_accounts(); s.ensure_seeded()
    print(count_users(), count_items(), count_points())
"""


def run(scenario):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tempfile.mkdtemp()}/seed.db"}
    out = subprocess.run([sys.executable, "-c", SCRIPT, scenario], env=env, capture_output=True, text=True, cwd=os.getcwd())
    assert out.returncode == 0, out.stderr
    return tuple(int(x) for x in out.stdout.split()[-3:])


def test_demo_login_on_empty_database_populates_items_and_points():
    users, items, points = run("demo_first")
    assert users == 7 and items == 18 and points == 4        # regressão: antes ficava 7, 0, 0


def test_home_first_unchanged():
    assert run("home_first") == (7, 18, 4)


def test_real_data_is_never_polluted_with_demo_items():
    users, items, points = run("real_user_first")
    assert users == 8 and items == 0 and points == 0         # usuário real: só as contas demo são garantidas
