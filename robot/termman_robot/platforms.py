from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from .contracts import RobotInboundMessage, RobotReplyTarget


@dataclass(frozen=True)
class BridgeRobot:
    id: str
    platform: str
    protocol: str
    provider: str
    name: str
    runtime_config: dict[str, Any]
    identity: str


def _normalize_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _credential_identity(platform_id: str, value: Any) -> str:
    normalized = _normalize_string(value)
    if normalized is None:
        raise ValueError(f"Platform `{platform_id}` identity is missing")
    return f"{platform_id}:{normalized}"


def _bot_self_id(bot: Any) -> str:
    self_id = getattr(bot, "self_id", None)
    if self_id is not None:
        return str(self_id)
    if hasattr(bot, "get_self_id"):
        value = bot.get_self_id()
        if not inspect.isawaitable(value):
            return str(value)
    raise ValueError("Bot self_id is missing")


def build_nonebot_init_kwargs(robots: list[BridgeRobot]) -> dict[str, Any]:
    init_kwargs: dict[str, Any] = {}
    for robot in robots:
        if robot.platform != "onebot_v11":
            continue
        credentials = robot.runtime_config["credentials"]
        access_token = _normalize_string(credentials.get("access_token"))
        secret = _normalize_string(credentials.get("secret"))
        if access_token is not None:
            existing = init_kwargs.get("onebot_access_token")
            if existing is not None and existing != access_token:
                raise ValueError(
                    "Conflicting shared adapter config for `onebot_access_token`"
                )
            init_kwargs["onebot_access_token"] = access_token
        if secret is not None:
            existing = init_kwargs.get("onebot_secret")
            if existing is not None and existing != secret:
                raise ValueError(
                    "Conflicting shared adapter config for `onebot_secret`"
                )
            init_kwargs["onebot_secret"] = secret
    return init_kwargs


def register_nonebot_adapters(driver: Any, robots: list[BridgeRobot]) -> None:
    del robots

    from nonebot.adapters.onebot.v11 import Adapter

    driver.register_adapter(Adapter)


def resolve_platform_from_bot(bot: Any) -> str | None:
    adapter_name = str(bot.adapter.get_name()).strip().lower()
    if adapter_name == "onebot v11":
        return "onebot_v11"
    return None


def resolve_bot_identity(bot: Any) -> str:
    platform_id = resolve_platform_from_bot(bot)
    if platform_id is None:
        raise ValueError("Unsupported bot adapter")
    return _credential_identity(platform_id, _bot_self_id(bot))


def _extract_event_text(event: Any) -> str:
    get_plaintext = getattr(event, "get_plaintext", None)
    if callable(get_plaintext):
        return str(get_plaintext() or "").strip()

    get_message = getattr(event, "get_message", None)
    if callable(get_message):
        message = get_message()
        extract_plain_text = getattr(message, "extract_plain_text", None)
        if callable(extract_plain_text):
            return str(extract_plain_text() or "").strip()
        return str(message or "").strip()

    return str(getattr(event, "message", "") or "").strip()


def _extract_sender_key(
    platform_id: str,
    event: Any,
    target_data: dict[str, Any],
) -> str:
    get_user_id = getattr(event, "get_user_id", None)
    user_id = ""
    if callable(get_user_id):
        try:
            user_id = str(get_user_id() or "")
        except Exception:
            user_id = ""

    target_id = str(target_data.get("id") or "")
    parent_id = str(target_data.get("parent_id") or "")
    if bool(target_data.get("private")):
        return f"{platform_id}:private:{user_id or target_id}"
    scope = "channel" if bool(target_data.get("channel")) else "group"
    return f"{platform_id}:{scope}:{parent_id or target_id}:{user_id or target_id}"


def _event_user_id(event: Any) -> str:
    get_user_id = getattr(event, "get_user_id", None)
    if callable(get_user_id):
        try:
            return str(get_user_id() or "").strip()
        except Exception:
            return ""
    return str(getattr(event, "user_id", "") or "").strip()


def _dump_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)

    for method_name in ("model_dump", "dict"):
        dump_method = getattr(value, method_name, None)
        if callable(dump_method):
            try:
                dumped = dump_method()
            except Exception:
                continue
            if isinstance(dumped, dict):
                return dict(dumped)

    return {}


def _extract_sender_metadata(platform_id: str, event: Any) -> dict[str, Any]:
    sender_data = _dump_mapping(getattr(event, "sender", None))
    user_id = _event_user_id(event) or str(sender_data.get("user_id") or "").strip()
    nickname = str(sender_data.get("nickname") or "").strip()
    card = str(sender_data.get("card") or "").strip()
    display_name = card or nickname or user_id

    metadata: dict[str, Any] = {
        "platform": platform_id,
        "user_id": user_id,
        "display_name": display_name,
    }
    if nickname:
        metadata["nickname"] = nickname
    if card:
        metadata["card"] = card

    for key in ("role", "title", "sex", "age", "area", "level"):
        value = sender_data.get(key)
        if value not in (None, ""):
            metadata[key] = value

    message_type = str(getattr(event, "message_type", "") or "").strip()
    if message_type:
        metadata["message_type"] = message_type
    return {key: value for key, value in metadata.items() if value not in (None, "")}


def _bot_self_ids(bot: Any, event: Any) -> set[str]:
    values = [
        getattr(bot, "self_id", None),
        getattr(bot, "user_id", None),
        getattr(bot, "id", None),
        getattr(event, "self_id", None),
    ]
    return {str(value).strip() for value in values if str(value or "").strip()}


def _event_message_segments(event: Any) -> list[Any]:
    get_message = getattr(event, "get_message", None)
    message = get_message() if callable(get_message) else getattr(event, "message", None)
    if message is None or isinstance(message, str):
        return []

    try:
        return list(message)
    except TypeError:
        return []


def _segment_type(segment: Any) -> str:
    if isinstance(segment, dict):
        return str(segment.get("type") or "").strip().lower()
    return str(getattr(segment, "type", "") or "").strip().lower()


def _segment_data(segment: Any) -> dict[str, Any]:
    data = segment.get("data") if isinstance(segment, dict) else getattr(segment, "data", None)
    return data if isinstance(data, dict) else {}


def _raw_message_mentions_bot(event: Any, self_ids: set[str]) -> bool:
    raw_message = str(getattr(event, "raw_message", "") or "")
    return any(
        f"[CQ:at,qq={self_id}]" in raw_message
        or f"[CQ:at,qq={self_id}," in raw_message
        for self_id in self_ids
    )


def _candidate_reply_sender_ids(reply_data: dict[str, Any]) -> set[str]:
    sender = reply_data.get("sender")
    sender_data = sender if isinstance(sender, dict) else _dump_mapping(sender)
    candidates = {
        reply_data.get("self_id"),
        reply_data.get("sender_id"),
        reply_data.get("user_id"),
        reply_data.get("message_sender_id"),
        sender_data.get("self_id"),
        sender_data.get("sender_id"),
        sender_data.get("user_id"),
        sender_data.get("id"),
    }
    return {str(value).strip() for value in candidates if str(value or "").strip()}


def _event_replies_to_bot(bot: Any, event: Any) -> bool:
    self_ids = _bot_self_ids(bot, event)
    if not self_ids:
        return False

    reply_data = _dump_mapping(getattr(event, "reply", None))
    if _candidate_reply_sender_ids(reply_data).intersection(self_ids):
        return True

    for segment in _event_message_segments(event):
        if _segment_type(segment) != "reply":
            continue
        if _candidate_reply_sender_ids(_segment_data(segment)).intersection(self_ids):
            return True

    return False


def _event_mentions_bot(bot: Any, event: Any) -> bool:
    to_me = getattr(event, "to_me", False)
    if callable(to_me):
        try:
            to_me = to_me()
        except Exception:
            to_me = False
    if bool(to_me):
        return True

    self_ids = _bot_self_ids(bot, event)
    if not self_ids:
        return False

    for segment in _event_message_segments(event):
        if _segment_type(segment) != "at":
            continue
        mention_id = _segment_data(segment).get("qq")
        if str(mention_id or "").strip() in self_ids:
            return True

    return _raw_message_mentions_bot(event, self_ids)


def build_inbound_message(
    platform_id: str,
    bot: Any,
    event: Any,
) -> RobotInboundMessage | None:
    text = _extract_event_text(event)
    if not text:
        return None

    from nonebot_plugin_alconna import get_message_id, get_target

    target = get_target(event, bot)
    target_data = target.dump()
    target_data["source"] = target.source or get_message_id(event, bot)
    metadata: dict[str, Any] = {
        "target": target_data,
        "sender": _extract_sender_metadata(platform_id, event),
    }
    if _event_mentions_bot(bot, event):
        metadata["mentioned_bot"] = True
    if _event_replies_to_bot(bot, event):
        metadata["replied_to_bot"] = True

    return RobotInboundMessage(
        sender_key=_extract_sender_key(platform_id, event, target_data),
        text=text,
        reply_target=RobotReplyTarget(
            target_type="universal",
            target_id=str(target.id),
            metadata=metadata,
        ),
    )


def _normalize_onebot_target_id(value: str) -> int | str:
    normalized = str(value or "").strip()
    return int(normalized) if normalized.isdigit() else normalized


async def _send_onebot_text_with_explicit_target(
    bot: Any,
    target: RobotReplyTarget,
    text: str,
) -> bool:
    adapter_name = str(bot.adapter.get_name()).strip().lower()
    if adapter_name != "onebot v11":
        return False

    connections = getattr(bot.adapter, "connections", {})
    self_id = str(getattr(bot, "self_id", "") or "")
    if self_id not in connections:
        raise ConnectionError(
            "OneBot reverse WebSocket is not connected; "
            "NapCat may have disconnected before the message was sent"
        )

    target_type = str(target.target_type or "").strip().lower()
    target_id = _normalize_onebot_target_id(target.target_id)
    if target_type == "group":
        await bot.call_api(
            "send_group_msg",
            group_id=target_id,
            message=text,
        )
        return True
    if target_type in {"private", "c2c", "friend", "direct", "direct_message"}:
        await bot.call_api(
            "send_private_msg",
            user_id=target_id,
            message=text,
        )
        return True
    return False


async def send_text_with_bot(
    bot: Any,
    target: RobotReplyTarget,
    text: str,
) -> None:
    normalized_text = (text or "").strip()
    if not normalized_text:
        return

    target_data = target.metadata.get("target")
    if isinstance(target_data, dict):
        adapter_name = str(bot.adapter.get_name()).strip().lower()
        if adapter_name == "onebot v11":
            connections = getattr(bot.adapter, "connections", {})
            self_id = str(getattr(bot, "self_id", "") or "")
            if self_id not in connections:
                raise ConnectionError(
                    "OneBot reverse WebSocket is not connected; "
                    "NapCat may have disconnected before the reply was sent"
                )

        from nonebot_plugin_alconna import UniMessage
        from nonebot_plugin_alconna.uniseg import Target

        loaded_target_data = dict(target_data)
        source = str(loaded_target_data.pop("source", "") or "")
        uni_target = Target.load(loaded_target_data)
        if source:
            uni_target.source = source
        await UniMessage(normalized_text).send(target=uni_target, bot=bot)
        return

    if await _send_onebot_text_with_explicit_target(bot, target, normalized_text):
        return

    raise ValueError("Unsupported reply target for current bot")
