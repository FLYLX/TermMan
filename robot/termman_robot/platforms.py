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
        ws_url = _normalize_string(credentials.get("ws_url"))
        if ws_url:
            init_kwargs.setdefault("onebot_ws_urls", set()).add(ws_url)
        api_root = _normalize_string(credentials.get("api_root"))
        if api_root is not None:
            init_kwargs.setdefault("onebot_api_roots", {})[
                str(credentials["self_id"])
            ] = api_root
    return init_kwargs


def register_nonebot_adapters(driver: Any, robots: list[BridgeRobot]) -> None:
    if not any(robot.platform == "onebot_v11" for robot in robots):
        return
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
    metadata: dict[str, Any] = {"target": target_data}

    return RobotInboundMessage(
        sender_key=_extract_sender_key(platform_id, event, target_data),
        text=text,
        reply_target=RobotReplyTarget(
            target_type="universal",
            target_id=str(target.id),
            metadata=metadata,
        ),
    )


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
        from nonebot_plugin_alconna import UniMessage
        from nonebot_plugin_alconna.uniseg import Target

        loaded_target_data = dict(target_data)
        source = str(loaded_target_data.pop("source", "") or "")
        uni_target = Target.load(loaded_target_data)
        if source:
            uni_target.source = source
        await UniMessage(normalized_text).send(target=uni_target, bot=bot)
        return

    raise ValueError("Unsupported reply target for current bot")
