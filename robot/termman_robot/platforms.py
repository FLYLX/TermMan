from __future__ import annotations

import inspect
import re
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


def _event_attr_text(event: Any, name: str) -> str:
    return str(getattr(event, name, "") or "").strip()


def _clean_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "")}


def _extract_conversation_metadata(
    platform_id: str,
    event: Any,
    target_data: dict[str, Any],
) -> dict[str, Any]:
    user_id = _event_user_id(event)
    message_type = _event_attr_text(event, "message_type").lower()
    group_id = _event_attr_text(event, "group_id")
    guild_id = _event_attr_text(event, "guild_id")
    channel_id = _event_attr_text(event, "channel_id")
    target_id = str(target_data.get("id") or "").strip()
    parent_id = str(target_data.get("parent_id") or "").strip()

    if platform_id == "onebot_v11":
        if message_type == "private" or bool(target_data.get("private")):
            conversation_id = user_id or target_id
            return _clean_mapping(
                {
                    "platform": platform_id,
                    "type": "private",
                    "id": conversation_id,
                    "target_type": "private",
                    "target_id": conversation_id,
                    "user_id": user_id,
                    "message_type": message_type or "private",
                }
            )
        if group_id or message_type == "group":
            conversation_id = group_id or parent_id or target_id
            return _clean_mapping(
                {
                    "platform": platform_id,
                    "type": "group",
                    "id": conversation_id,
                    "target_type": "group",
                    "target_id": conversation_id,
                    "group_id": group_id,
                    "user_id": user_id,
                    "message_type": message_type or "group",
                }
            )

    if bool(target_data.get("private")):
        conversation_id = user_id or target_id
        return _clean_mapping(
            {
                "platform": platform_id,
                "type": "private",
                "id": conversation_id,
                "target_type": "private",
                "target_id": conversation_id,
                "user_id": user_id,
                "message_type": message_type or "private",
            }
        )
    if bool(target_data.get("channel")):
        conversation_id = parent_id or channel_id or target_id
        return _clean_mapping(
            {
                "platform": platform_id,
                "type": "channel",
                "id": conversation_id,
                "target_type": "channel",
                "target_id": channel_id or target_id,
                "guild_id": guild_id or parent_id,
                "channel_id": channel_id or target_id,
                "user_id": user_id,
                "message_type": message_type or "channel",
            }
        )

    conversation_id = group_id or parent_id or target_id
    return _clean_mapping(
        {
            "platform": platform_id,
            "type": "group",
            "id": conversation_id,
            "target_type": "group",
            "target_id": conversation_id,
            "group_id": group_id,
            "user_id": user_id,
            "message_type": message_type or "group",
        }
    )


def _extract_sender_key(
    platform_id: str,
    event: Any,
    target_data: dict[str, Any],
    conversation_data: dict[str, Any] | None = None,
) -> str:
    conversation_data = conversation_data or {}
    user_id = str(conversation_data.get("user_id") or _event_user_id(event)).strip()
    conversation_type = str(conversation_data.get("type") or "").strip().lower()
    conversation_id = str(conversation_data.get("id") or "").strip()
    if conversation_type and conversation_id:
        if conversation_type == "private":
            return f"{platform_id}:private:{user_id or conversation_id}"
        return f"{platform_id}:{conversation_type}:{conversation_id}:{user_id or conversation_id}"

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


def _clean_mention_value(value: Any) -> str:
    return str(value or "").strip()


def _mention_from_data(data: dict[str, Any]) -> dict[str, str] | None:
    mention_id = _clean_mention_value(
        data.get("qq") or data.get("id") or data.get("user_id")
    )
    if not mention_id:
        return None

    mention: dict[str, str] = {"id": mention_id, "qq": mention_id}
    name = _clean_mention_value(
        data.get("name")
        or data.get("display_name")
        or data.get("nickname")
        or data.get("card")
    )
    if name:
        mention["name"] = name
    return mention


def _append_mention(mentions: list[dict[str, str]], mention: dict[str, str]) -> None:
    mention_id = mention.get("id", "")
    for existing in mentions:
        if existing.get("id") != mention_id:
            continue
        if mention.get("name") and not existing.get("name"):
            existing["name"] = mention["name"]
        return
    mentions.append(mention)


def _parse_cq_params(raw_params: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for part in raw_params.split(","):
        key, separator, value = part.partition("=")
        if separator:
            params[key.strip()] = value.strip()
    return params


def _extract_event_mentions(event: Any) -> list[dict[str, str]]:
    mentions: list[dict[str, str]] = []
    for segment in _event_message_segments(event):
        if _segment_type(segment) != "at":
            continue
        mention = _mention_from_data(_segment_data(segment))
        if mention is not None:
            _append_mention(mentions, mention)

    raw_message = str(getattr(event, "raw_message", "") or "")
    for match in re.finditer(r"\[CQ:at,([^\]]+)\]", raw_message):
        mention = _mention_from_data(_parse_cq_params(match.group(1)))
        if mention is not None:
            _append_mention(mentions, mention)
    return mentions


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
    conversation_data = _extract_conversation_metadata(platform_id, event, target_data)
    for key in ("message_type", "group_id", "user_id", "guild_id", "channel_id"):
        value = conversation_data.get(key)
        if value not in (None, ""):
            target_data.setdefault(key, value)
    metadata: dict[str, Any] = {
        "target": target_data,
        "sender": _extract_sender_metadata(platform_id, event),
        "conversation": conversation_data,
    }
    mentions = _extract_event_mentions(event)
    if mentions:
        metadata["mentions"] = mentions
    if _event_mentions_bot(bot, event):
        metadata["mentioned_bot"] = True
    if _event_replies_to_bot(bot, event):
        metadata["replied_to_bot"] = True

    return RobotInboundMessage(
        sender_key=_extract_sender_key(
            platform_id,
            event,
            target_data,
            conversation_data=conversation_data,
        ),
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


def _prepare_unimessage_target_data(target_data: dict[str, Any]) -> tuple[dict[str, Any], str]:
    loaded_target_data = dict(target_data)
    source = str(loaded_target_data.pop("source", "") or "")
    for key in ("message_type", "group_id", "user_id", "guild_id", "channel_id"):
        loaded_target_data.pop(key, None)
    return loaded_target_data, source


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

        loaded_target_data, source = _prepare_unimessage_target_data(target_data)
        uni_target = Target.load(loaded_target_data)
        if source:
            uni_target.source = source
        await UniMessage(normalized_text).send(target=uni_target, bot=bot)
        return

    if await _send_onebot_text_with_explicit_target(bot, target, normalized_text):
        return

    raise ValueError("Unsupported reply target for current bot")
