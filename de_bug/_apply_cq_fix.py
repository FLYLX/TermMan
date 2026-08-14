import io, sys

path = r"E:\dev\TermPaws\dev\TermPaws\robot\TermPaws_robot\platforms.py"
with io.open(path, "r", encoding="utf-8") as handle:
    text = handle.read()

helpers = '''_CQ_AT_PATTERN = re.compile(r"\\[CQ:at,([^\\]]+)\\]")


def _append_onebot_text_segment(
    segments: list[dict[str, dict[str, str]]],
    text: str,
) -> None:
    if not text:
        return
    if segments and segments[-1].get("type") == "text":
        segments[-1]["data"]["text"] += text
        return
    segments.append({"type": "text", "data": {"text": text}})


def _onebot_group_message_payload(text: str) -> str | list[dict[str, dict[str, str]]]:
    normalized_text = str(text or "")
    segments: list[dict[str, dict[str, str]]] = []
    has_at_segment = False
    cursor = 0

    for match in _CQ_AT_PATTERN.finditer(normalized_text):
        _append_onebot_text_segment(segments, normalized_text[cursor : match.start()])
        params = _parse_cq_params(match.group(1))
        qq = str(params.get("qq") or "").strip()
        if qq:
            segments.append({"type": "at", "data": {"qq": qq}})
            has_at_segment = True
        else:
            _append_onebot_text_segment(segments, match.group(0))
        cursor = match.end()

    if not has_at_segment:
        return normalized_text

    _append_onebot_text_segment(segments, normalized_text[cursor:])
    return segments


def _onebot_group_id_from_target_data(target_data: dict[str, Any]) -> int | str | None:
    message_type = str(target_data.get("message_type") or "").strip().lower()
    group_id = str(target_data.get("group_id") or "").strip()
    if message_type == "group":
        group_id = group_id or str(
            target_data.get("parent_id") or target_data.get("id") or ""
        ).strip()
    if not group_id:
        return None
    return _normalize_onebot_target_id(group_id)


def _prepare_unimessage_target_data'''

anchor1 = "def _prepare_unimessage_target_data"
assert text.count(anchor1) == 1, "anchor1 count=%d" % text.count(anchor1)
assert "_onebot_group_message_payload" not in text, "already patched"
text = text.replace(anchor1, helpers, 1)

anchor2 = '''    if target_type == "group":
        await bot.call_api(
            "send_group_msg",
            group_id=target_id,
            message=text,
        )
        return True'''
replacement2 = '''    if target_type == "group":
        await bot.call_api(
            "send_group_msg",
            group_id=target_id,
            message=_onebot_group_message_payload(text),
        )
        return True'''
assert text.count(anchor2) == 1, "anchor2 count=%d" % text.count(anchor2)
text = text.replace(anchor2, replacement2, 1)

anchor3 = '''                    "The QQ connector may have disconnected before the reply was sent"
                )

        from nonebot_plugin_alconna import UniMessage'''
replacement3 = '''                    "The QQ connector may have disconnected before the reply was sent"
                )

        onebot_group_id = (
            _onebot_group_id_from_target_data(target_data)
            if adapter_name == "onebot v11"
            else None
        )
        if onebot_group_id is not None:
            group_payload = _onebot_group_message_payload(normalized_text)
            if not isinstance(group_payload, str):
                await bot.call_api(
                    "send_group_msg",
                    group_id=onebot_group_id,
                    message=group_payload,
                )
                return

        from nonebot_plugin_alconna import UniMessage'''
assert text.count(anchor3) == 1, "anchor3 count=%d" % text.count(anchor3)
text = text.replace(anchor3, replacement3, 1)

with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(text)
print("PATCHED OK")