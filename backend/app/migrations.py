"""Additive schema migrations for the SQLite database.

``Base.metadata.create_all`` creates *missing tables* but never touches a
table that already exists, so a database written by an earlier version keeps
its old columns and every query for a new one fails.  This module closes that
gap in the only way that is safe for a file the user already has data in:

* new tables are created,
* new columns are added with ``ALTER TABLE ... ADD COLUMN``,
* nothing is ever dropped, renamed, re-typed or rewritten.

That makes the change backward compatible - an older build still reads the
database, because every added column is nullable or carries a default.  To
apply it, simply start the application; :func:`run_migrations` runs on
startup.  Columns that SQLite cannot add in place are reported rather than
forced, so no data is lost to a migration.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .database import Base

logger = logging.getLogger(__name__)

#: SQLite only accepts a constant default on ADD COLUMN.
_DEFAULTS = {
    "JSON": "'[]'",
    "BOOLEAN": "0",
    "INTEGER": "0",
    "FLOAT": "NULL",
}


def _column_sql(column) -> str | None:
    """DDL for one added column, or ``None`` when it cannot be added safely."""
    try:
        type_sql = column.type.compile(dialect=None)
    except Exception:  # noqa: BLE001 - dialect-specific types
        type_sql = str(column.type)

    parts = [f'"{column.name}"', type_sql]

    if not column.nullable:
        default = None
        if column.default is not None and getattr(column.default, "is_scalar", False):
            value = column.default.arg
            default = f"'{value}'" if isinstance(value, str) else str(int(value))
        else:
            default = _DEFAULTS.get(type_sql.upper())

        if default is None or default == "NULL":
            # A NOT NULL column with no usable default cannot be added to a
            # populated table without inventing data, so it is refused.
            return None
        parts.append(f"NOT NULL DEFAULT {default}")
    elif column.default is not None and getattr(column.default, "is_scalar", False):
        value = column.default.arg
        if isinstance(value, (list, dict)):
            parts.append(f"DEFAULT '{'[]' if isinstance(value, list) else '{}'}'")
        elif isinstance(value, str):
            parts.append(f"DEFAULT '{value}'")
        elif isinstance(value, bool):
            parts.append(f"DEFAULT {int(value)}")
        elif isinstance(value, (int, float)):
            parts.append(f"DEFAULT {value}")

    return " ".join(parts)


def pending_changes(engine: Engine) -> dict[str, list[str]]:
    """Report what :func:`run_migrations` would do, without doing it."""
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())

    plan: dict[str, list[str]] = {"create_table": [], "add_column": [], "blocked": []}

    for name, table in Base.metadata.tables.items():
        if name not in existing:
            plan["create_table"].append(name)
            continue

        have = {c["name"] for c in inspector.get_columns(name)}
        for column in table.columns:
            if column.name in have:
                continue
            if _column_sql(column) is None:
                plan["blocked"].append(f"{name}.{column.name}")
            else:
                plan["add_column"].append(f"{name}.{column.name}")

    return plan


def run_migrations(engine: Engine) -> dict[str, list[str]]:
    """Bring an existing database up to the current schema, additively."""
    # Creates any table that does not exist; existing tables are untouched.
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    applied: dict[str, list[str]] = {"added": [], "blocked": []}

    for name, table in Base.metadata.tables.items():
        if name not in existing:
            continue  # just created with the full definition

        have = {c["name"] for c in inspector.get_columns(name)}
        for column in table.columns:
            if column.name in have:
                continue

            ddl = _column_sql(column)
            if ddl is None:
                applied["blocked"].append(f"{name}.{column.name}")
                logger.error(
                    "Cannot add %s.%s automatically: NOT NULL without a default. "
                    "Add it by hand before using this build.", name, column.name,
                )
                continue

            statement = f'ALTER TABLE "{name}" ADD COLUMN {ddl}'
            try:
                with engine.begin() as connection:
                    connection.execute(text(statement))
            except Exception as exc:  # noqa: BLE001 - report, never crash startup
                applied["blocked"].append(f"{name}.{column.name}")
                logger.error("Migration failed (%s): %s", statement, exc)
                continue

            applied["added"].append(f"{name}.{column.name}")
            logger.info("Added column %s.%s", name, column.name)

    return applied
