from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from robot.termpaws_robot.platforms import build_inbound_message


@dataclass
class _Segment:
    type: str
    data: dict[str, str]


class _Message(list):
    def extract_plain_text(self) -> str:
        return "".join(
            str(segment.data.get("text") or "")
            for segment in self
            if segment.type == "text"
        )


class _Target:
    id = "123456"
    source = "message-2"

    def dump(self) -> dict[str, object]:
        return {"id": self.id, "parent_id": self.id}


class _Bot:
    self_id = "10001"


class _Event:
    self_id = "10001"
    user_id = "10002"
    message_type = "group"
    group_id = "123456"
    raw_message = "[CQ:reply,id=message-1]is it running?"
    sender = {"user_id": "10002", "nickname": "Alice", "card": "Alice"}
    reply = {
        "message_id": "message-1",
        "sender": {"user_id": "10001", "nickname": "Bot"},
        "message": [_Segment("text", {"text": "run.sh is ready, start it?"})],
    }

    def get_user_id(self) -> str:
        return self.user_id

    def get_message(self) -> _Message:
        return _Message(
            [
                _Segment("reply", {"id": "message-1", "qq": "10001"}),
                _Segment("text", {"text": "is it running?"}),
            ]
        )

    def get_plaintext(self) -> str:
        return "is it running?"


def test_bridge_keeps_napcat_replied_message_context(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "nonebot_plugin_alconna",
        types.SimpleNamespace(
            get_message_id=lambda _event, _bot: "message-2",
            get_target=lambda _event, _bot: _Target(),
        ),
    )

    inbound = build_inbound_message("onebot_v11", _Bot(), _Event())

    assert inbound is not None
    assert inbound.reply_target.metadata["replied_to_bot"] is True
    assert inbound.reply_target.metadata["reply"] == {
        "message_id": "message-1",
        "source": "message-1",
        "text": "run.sh is ready, start it?",
        "sender": {
            "user_id": "10001",
            "display_name": "Bot",
            "nickname": "Bot",
        },
        "segment": {"id": "message-1", "qq": "10001"},
        "raw_segment": {"id": "message-1"},
    }
