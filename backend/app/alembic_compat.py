from __future__ import annotations

import sys
from collections.abc import Mapping

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.core.db import engine

REVISION_HEAD = "dc16467db813"

CURRENT_SCHEMA_COLUMNS: dict[str, set[str]] = {
    "user": {
        "email",
        "is_active",
        "is_superuser",
        "full_name",
        "id",
        "hashed_password",
        "created_at",
    },
    "item": {
        "title",
        "description",
        "status",
        "log_max_size_mb",
        "socket_host",
        "socket_port",
        "socket_connected",
        "socket_last_connected",
        "api_key",
        "command",
        "working_directory",
        "input_filter_enabled",
        "input_filter_rules",
        "output_filter_enabled",
        "output_filter_rules",
        "id",
        "created_at",
        "updated_at",
        "owner_id",
    },
    "itemhandler": {
        "name",
        "model",
        "api_key",
        "api_url",
        "enabled_skills",
        "enabled_mcp_servers",
        "enabled_knowledge_files",
        "id",
        "created_at",
        "updated_at",
        "owner_id",
    },
    "itemchatsession": {
        "messages",
        "id",
        "item_id",
        "created_at",
        "updated_at",
    },
    "itemhandleritem": {
        "item_handler_id",
        "item_id",
    },
    "itemhandleruser": {
        "item_handler_id",
        "user_id",
    },
    "robot": {
        "name",
        "platform",
        "protocol",
        "provider",
        "app_id",
        "app_secret",
        "bot_token",
        "use_websocket",
        "is_enabled",
        "config",
        "id",
        "created_at",
        "updated_at",
        "owner_id",
    },
    "robotitem": {
        "robot_id",
        "item_id",
        "allow_chat",
        "receive_filtered_output",
        "chat_alias",
        "is_default_target",
    },
}


def _ensure_current_schema_shape(schema: Mapping[str, set[str]]) -> None:
    for table_name, expected_columns in CURRENT_SCHEMA_COLUMNS.items():
        actual_columns = schema.get(table_name)
        if actual_columns is None:
            raise RuntimeError(
                f"Legacy database is missing required table '{table_name}'."
            )
        if not expected_columns.issubset(actual_columns):
            missing = sorted(expected_columns - actual_columns)
            raise RuntimeError(
                f"Legacy database table '{table_name}' is missing columns: {', '.join(missing)}."
            )


def infer_legacy_revision_from_schema(schema: Mapping[str, set[str]]) -> str | None:
    if "alembic_version" in schema:
        return None

    app_tables = set(CURRENT_SCHEMA_COLUMNS) & set(schema)
    if not app_tables:
        return None

    _ensure_current_schema_shape(schema)
    return REVISION_HEAD


def detect_legacy_revision(db_engine: Engine) -> str | None:
    inspector = inspect(db_engine)
    schema: dict[str, set[str]] = {}
    for table_name in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        schema[table_name] = columns
    return infer_legacy_revision_from_schema(schema)


def main() -> int:
    try:
        revision = detect_legacy_revision(engine)
    except RuntimeError as exc:
        sys.stderr.write(f"[AlembicCompat] {exc}\n")
        return 1

    if revision:
        sys.stdout.write(f"{revision}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
