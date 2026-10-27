"""
    python init_db.py              # cria o banco se não existir e aplica o schema
    python init_db.py --reset      # APAGA todas as tabelas e recria (só em banco LOCAL)
    python init_db.py --seed       # além disso, insere dados de exemplo (só em banco LOCAL)
"""
import argparse
import os
import sys
from contextlib import closing
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from sqlalchemy.engine import make_url

SCHEMA_FILE = Path(__file__).parent / "sql" / "schema.sql"
HOSTS_LOCAIS = {None, "", "localhost", "127.0.0.1", "::1"}

def banco_local(raw_url: str) -> bool:
    return make_url(raw_url).host in HOSTS_LOCAIS

def _conectar(url, dbname: str):
    conn = psycopg2.connect(
        host=url.host, port=url.port or 5432, user=url.username,
        password=url.password, dbname=dbname, **dict(url.query))
    conn.autocommit = True
    return conn

def preparar_banco(raw_url: str, reset: bool = False) -> None:
    url = make_url(raw_url)
    if reset and not banco_local(raw_url):
        raise RuntimeError(
            f"--reset recusado: '{url.host}' não é um banco local. "
    # 1) cria o banco, se ainda não existir
    with closing(_conectar(url, "postgres")) as admin, admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (url.database,))
        if not cur.fetchone():
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(url.database)))
            print(f"Banco '{url.database}' criado.")

    # 2) aplica o schema
    with closing(_conectar(url, url.database)) as conn, conn.cursor() as cur:
        if reset:
            cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            print("Schema anterior removido (--reset).")
        cur.execute("SELECT to_regclass('public.usuario')")
        if cur.fetchone()[0]:
            print("O schema já existe. Nada a fazer (use --reset para recriar).")
        else:
            cur.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
            print("Schema aplicado com sucesso.")

def main() -> int:
    parser = argparse.ArgumentParser(description="Inicializa o banco do EsqueceramAI")
    parser.add_argument("--reset", action="store_true", help="apaga tudo e recria o schema")
    parser.add_argument("--seed", action="store_true", help="insere dados de exemplo")
    args = parser.parse_args()

    load_dotenv()
    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        print("ERRO: defina DATABASE_URL no arquivo .env (veja .env.example)")
        return 1

    try:
        preparar_banco(raw_url, reset=args.reset)
        if args.seed:
            from seed import run_seed
            run_seed()
    except RuntimeError as erro:
        print(f"ERRO: {erro}")
        return 1
    except psycopg2.errors.DuplicateTable as erro:
        print("ERRO: já existem tabelas deste projeto criadas à mão neste banco.\n"
              f"      Detalhe: {str(erro).strip()}\n"
              "      Nada foi alterado (o schema roda em uma transação).\n"
              "      - Banco só seu, dados descartáveis:  python init_db.py --reset\n"
              "      - Banco compartilhado: combine com a equipe antes de mexer nas tabelas.")
        return 1
    except psycopg2.OperationalError as erro:
        print("ERRO: não consegui conectar ao PostgreSQL. Confira:\n"
              "      1) o serviço do PostgreSQL está rodando;\n"
              "      2) usuário e senha do DATABASE_URL no arquivo .env;\n"
              f"      Detalhe: {str(erro).strip()}")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())