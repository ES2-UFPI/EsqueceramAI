import os
import psycopg2
from functools import lru_cache

class DatabaseConnection:
    @staticmethod
    def _get_url():
        value = os.getenv("DATABASE_URL")
        if not value or "senha" in value:
            return None
        return value

    @classmethod
    @lru_cache(maxsize=1)
    def get_connection(cls):
        url = cls._get_url()
        if not url:
            return None
        return psycopg2.connect(url)
