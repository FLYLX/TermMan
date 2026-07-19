from app.plugins.robot.memory_migration import (
    ROBOT_MEMORY_SCHEMA_VERSION,
    build_legacy_memory_metadata_upgrade,
    ensure_legacy_robot_memories_upgraded,
)


def test_memory_migration_repairs_old_relation_fact_scope() -> None:
    memory = {
        "id": "memory-1",
        "content": "群770362397中设定：猫娘为月影汉堡，QQ号3385417251",
        "metadata": {
            "memory_type": "fact",
            "memory_scope": "speaker",
            "robot_conversation_key": "group:770362397",
            "speaker_global_key": "onebot_v11:user:2206406352",
            "robot_memory_schema_version": 2,
        },
    }

    updates = build_legacy_memory_metadata_upgrade(memory)

    assert updates["robot_memory_schema_version"] == ROBOT_MEMORY_SCHEMA_VERSION
    assert updates["memory_scope"] == "conversation"
    assert updates["robot_conversation_key"] == "group:770362397"


def test_memory_migration_removes_exact_import_copy_and_upgrades_original() -> None:
    original = {
        "id": "original",
        "content": "月影寒波（简称汉堡）是猫娘",
        "metadata": {
            "memory_type": "fact",
            "memory_scope": "speaker",
            "robot_conversation_key": "group:770362397",
            "robot_memory_schema_version": 2,
        },
    }
    imported = {
        "id": "imported",
        "content": original["content"],
        "metadata": {
            **original["metadata"],
            "imported_from_memory_id": "original",
        },
    }

    class FakeStore:
        def __init__(self) -> None:
            self.deleted: list[str] = []
            self.updated: dict[str, dict] = {}

        def get_all_memories(self, _item_id: str):
            return [original, imported]

        def delete_memory(self, memory_id: str) -> bool:
            self.deleted.append(memory_id)
            return True

        def update_memory_metadata(self, memory_id: str, metadata: dict) -> bool:
            self.updated[memory_id] = metadata
            return True

    store = FakeStore()
    result = ensure_legacy_robot_memories_upgraded(
        "item-migration-test",
        store=store,
        interval_seconds=0,
    )

    assert result == {"checked": 2, "upgraded": 1, "deduplicated": 1, "failed": 0}
    assert store.deleted == ["imported"]
    assert store.updated["original"]["memory_scope"] == "conversation"
