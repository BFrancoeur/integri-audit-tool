"""Raw catalog SQL for the Backup, Recovery & Change Management category.

Most of this category's rubric bullets ask about external process and
tooling — whether backups are tested, whether an RTO/RPO is documented,
whether a staging environment exists — none of which is visible from inside
the database. What Postgres *does* expose are a few honest, partial signals:
pg_stat_archiver (WAL archiving health — a real, concrete indicator that
continuous-archiving-based backups are or aren't succeeding), heuristic
detection of well-known migration-tool tracking tables, and pg_stat_replication
(whether anything is currently streaming from this instance, one possible
signal of a staging/replica topology). None of these prove or disprove the
full rubric bullet on their own — checks.py treats most of them as evidence
to surface, not a verdict.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

# Table names used by common migration tools' tracking tables, lowercased
# for case-insensitive matching (some ORMs create these with quoted mixed
# case, e.g. EF Core's "__EFMigrationsHistory").
KNOWN_MIGRATION_TABLE_NAMES = [
    "schema_migrations",  # Rails / ActiveRecord, golang-migrate
    "flyway_schema_history",  # Flyway
    "django_migrations",  # Django
    "alembic_version",  # Alembic / SQLAlchemy
    "knex_migrations",  # Knex.js
    "_prisma_migrations",  # Prisma
    "migrations",  # generic / TypeORM default
    "__efmigrationshistory",  # EF Core
    "goose_db_version",  # Goose
    "sequelizemeta",  # Sequelize
]

_WAL_ARCHIVER_STATUS_SQL = """
    SELECT
        archived_count,
        failed_count,
        last_archived_time,
        last_failed_time
    FROM pg_stat_archiver;
"""

_MIGRATION_TRACKING_TABLES_SQL = """
    SELECT
        n.nspname AS schema_name,
        c.relname AS table_name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'r'
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND lower(c.relname) = ANY(%(known_names)s)
    ORDER BY n.nspname, c.relname;
"""

_REPLICA_COUNT_SQL = """
    SELECT count(*) AS replica_count FROM pg_stat_replication;
"""


def fetch_wal_archiver_status(conn: psycopg.Connection) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_WAL_ARCHIVER_STATUS_SQL)
        return cur.fetchone()


def fetch_migration_tracking_tables(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_MIGRATION_TRACKING_TABLES_SQL, {"known_names": KNOWN_MIGRATION_TABLE_NAMES})
        return cur.fetchall()


def fetch_replica_count(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute(_REPLICA_COUNT_SQL)
        return cur.fetchone()[0]
