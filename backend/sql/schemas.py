"""Referência de esquema para ferramentas Python.

O esquema de produção é versionado pelo Supabase em
``supabase/migrations``. Este módulo mantém o caminho explícito para scripts
administrativos, sem executar SQL automaticamente no boot do Render.
"""
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
SUPABASE_MIGRATIONS_DIR = BACKEND_DIR.parent / "supabase" / "migrations"
LOCAL_SCHEMA_SQL = Path(__file__).with_name("schema.sql")


def migration_files() -> list[Path]:
    """Retorna migrações ordenadas que devem ser aplicadas pelo Supabase CLI."""
    return sorted(SUPABASE_MIGRATIONS_DIR.glob("*.sql"))
