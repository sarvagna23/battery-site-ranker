"""Small database helpers."""
import psycopg
from psycopg.rows import dict_row

from .config import load_settings


def connect(url: str | None = None):
    """Open a connection that returns rows as dicts."""
    return psycopg.connect(url or load_settings().database_url, row_factory=dict_row)
