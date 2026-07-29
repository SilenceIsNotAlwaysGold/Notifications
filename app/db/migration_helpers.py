from collections.abc import Iterable

from sqlalchemy import inspect
from sqlalchemy.engine import Connection


def table_exists(connection: Connection, table_name: str) -> bool:
    return inspect(connection).has_table(table_name)


def column_names(connection: Connection, table_name: str) -> set[str]:
    if not table_exists(connection, table_name):
        return set()
    return {str(column["name"]) for column in inspect(connection).get_columns(table_name)}


def index_details(connection: Connection, table_name: str) -> dict[str, dict]:
    if not table_exists(connection, table_name):
        return {}
    return {
        str(index["name"]): index
        for index in inspect(connection).get_indexes(table_name)
        if index.get("name")
    }


def index_names(connection: Connection, table_name: str) -> set[str]:
    return set(index_details(connection, table_name))


def has_foreign_key(
    connection: Connection,
    table_name: str,
    constrained_columns: Iterable[str],
    referred_table: str,
) -> bool:
    expected = tuple(constrained_columns)
    if not table_exists(connection, table_name):
        return False
    return any(
        tuple(foreign_key.get("constrained_columns") or ()) == expected
        and foreign_key.get("referred_table") == referred_table
        for foreign_key in inspect(connection).get_foreign_keys(table_name)
    )


def require_columns(connection: Connection, table_name: str, required: Iterable[str]) -> None:
    missing = set(required) - column_names(connection, table_name)
    if missing:
        names = ", ".join(sorted(missing))
        raise RuntimeError(f"Existing table {table_name!r} is missing required columns: {names}")
