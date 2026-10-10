"""Command line: python -m ranker.ingest [schema|counties|osm|queue|features|all|inspect-queue]"""
import sys
from pathlib import Path

from ..config import load_settings
from ..db import connect
from .counties import ingest_counties
from .osm import ingest_osm
from .queue import ingest_queue, inspect_queue

SQL_DIR = Path(__file__).resolve().parents[3] / "sql"
if not SQL_DIR.exists():  # inside the container the sql folder sits next to the package
    SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def run_sql_file(connection, name: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute((SQL_DIR / name).read_text())
    connection.commit()


def main() -> None:
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    settings = load_settings()
    if step == "inspect-queue":
        inspect_queue(settings)
        return
    with connect(settings.database_url) as connection:
        if step in ("schema", "all"):
            run_sql_file(connection, "schema.sql")
        if step in ("counties", "all"):
            ingest_counties(connection, settings)
        if step in ("osm", "all"):
            ingest_osm(connection, settings)
        if step in ("queue", "all"):
            ingest_queue(connection, settings)
        if step in ("features", "all"):
            run_sql_file(connection, "features.sql")
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS n FROM site_features")
                print(f"site_features rows: {cursor.fetchone()['n']}")
    print("Done.")


if __name__ == "__main__":
    main()
