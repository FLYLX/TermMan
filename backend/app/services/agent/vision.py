"""多模态图片输入：下载/转 base64/构造 vision content 块/模型能力检测。"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MAX_IMAGES_PER_TURN = 4
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_DOWNLOAD_TIMEOUT = 15.0
DATA_URL_PREFIX = "data:"


def supports_vision_model(model: str | None) -> bool:
    """litellm 的 vision 能力表；未知/代理模型按不支持处理（调用方可强制覆盖）。
    带 provider 前缀的名字同时尝试裸名（如 zhipu/glm-4v 与 glm-4v）。"""
    name = str(model or "").strip()
    if not name:
        return False
    try:
        import litellm

        if bool(litellm.supports_vision(model=name)):
            return True
        bare = name.rsplit("/", 1)[-1]
        if bare != name:
            return bool(litellm.supports_vision(model=bare))
        return False
    except Exception:
        return False


def _guess_mime(content_type: str, url: str) -> str | None:
    normalized = (content_type or "").split(";")[0].strip().lower()
    if normalized.startswith("image/"):
        return normalized
    lowered = url.lower().split("?")[0]
    for suffix, mime in (
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".png", "image/png"),
        (".gif", "image/gif"),
        (".webp", "image/webp"),
        (".bmp", "image/bmp"),
    ):
        if lowered.endswith(suffix):
            return mime
    return None


def fetch_image_as_data_url(url: str) -> str | None:
    """http(s) 图片下载转 data URL；data: 开头原样返回；本地缓存路径
    (/robots/images/<name>) 直接读盘。失败返回 None。"""
    url = str(url or "").strip()
    if not url:
        return None
    if url.startswith("data:image/"):
        return url
    if url.startswith(("/robots/images/", "/api/v1/robots/images/")):
        try:
            import mimetypes

            from app.plugins.robot.image_store import image_file_path

            path = image_file_path(url.rsplit("/", 1)[-1])
            if path is None:
                return None
            payload = path.read_bytes()
            if len(payload) > MAX_IMAGE_BYTES:
                return None
            mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
            encoded = base64.b64encode(payload).decode("ascii")
            return f"data:{mime};base64,{encoded}"
        except Exception as exc:
            logger.warning("[Vision] 本地缓存图片读取失败 %s: %s", url[:80], exc)
            return None
    if not url.startswith(("http://", "https://")):
        return None
    try:
        with httpx.Client(
            timeout=IMAGE_DOWNLOAD_TIMEOUT, follow_redirects=True
        ) as client:
            response = client.get(url)
            response.raise_for_status()
        mime = _guess_mime(response.headers.get("content-type", ""), url)
        if mime is None:
            logger.warning("[Vision] 非图片内容类型: %s (%s)", response.headers.get("content-type"), url[:80])
            return None
        payload = response.content
        if len(payload) > MAX_IMAGE_BYTES:
            logger.warning("[Vision] 图片过大 (%d bytes): %s", len(payload), url[:80])
            return None
        encoded = base64.b64encode(payload).decode("ascii")
        return f"{DATA_URL_PREFIX}{mime};base64,{encoded}"
    except Exception as exc:
        logger.warning("[Vision] 图片下载失败 %s: %s", url[:80], exc)
        return None


def build_user_content(
    text: str,
    image_urls: list[str] | None,
    *,
    vision_enabled: bool,
) -> str | list[dict[str, Any]]:
    """构造 LLM user message content。

    vision_enabled=False 或全部下载失败时退化为纯文本（附占位说明），
    有保证: 返回值可直接作为 OpenAI/litellm 消息的 content。
    """
    urls = [str(u).strip() for u in (image_urls or []) if str(u or "").strip()][
        :MAX_IMAGES_PER_TURN
    ]
    if not urls:
        return text
    if not vision_enabled:
        count = len(urls)
        note = f"[附带 {count} 张图片，当前未启用/不支持看图]"
        return f"{text}\n{note}" if text else note

    blocks: list[dict[str, Any]] = []
    if text.strip():
        blocks.append({"type": "text", "text": text})
    attached = 0
    for url in urls:
        data_url = fetch_image_as_data_url(url)
        if data_url is None:
            continue
        blocks.append({"type": "image_url", "image_url": {"url": data_url}})
        attached += 1
    if attached == 0:
        note = "[附带图片，但下载失败无法查看]"
        return f"{text}\n{note}" if text else note
    if attached < len(urls):
        blocks.append(
            {
                "type": "text",
                "text": f"[{len(urls) - attached} 张图片下载失败]",
            }
        )
    return blocks
