import pytest

from app.alembic_compat import REVISION_HEAD, infer_legacy_revision_from_schema

CURRENT_SCHEMA = {
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
    "itemchatsession": {"messages", "id", "item_id", "created_at", "updated_at"},
    "itemhandleritem": {"item_handler_id", "item_id"},
    "itemhandleruser": {"item_handler_id", "user_id"},
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


def test_infer_revision_none_for_empty_schema() -> None:
    assert infer_legacy_revision_from_schema({}) is None


def test_infer_revision_none_when_alembic_version_exists() -> None:
    assert infer_legacy_revision_from_schema({"alembic_version": {"version_num"}}) is None


def test_infer_head_revision_for_current_schema_without_alembic_version() -> None:
    assert infer_legacy_revision_from_schema(CURRENT_SCHEMA) == REVISION_HEAD


def test_infer_revision_fails_for_partial_schema() -> None:
    partial_schema = dict(CURRENT_SCHEMA)
    partial_schema.pop("robotitem")

    with pytest.raises(RuntimeError):
        infer_legacy_revision_from_schema(partial_schema)


def test_infer_revision_fails_when_table_is_missing_columns() -> None:
    partial_schema = dict(CURRENT_SCHEMA)
    partial_schema["itemhandler"] = set(CURRENT_SCHEMA["itemhandler"]) - {"enabled_knowledge_files"}

    with pytest.raises(RuntimeError):
        infer_legacy_revision_from_schema(partial_schema)
