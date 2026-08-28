"""QQ 入站图片的落盘缓存与本地服务。

NapCat 给的图片 URL（multimedia.nt.qq.com）rkey 会过期、且对浏览器有
防盗链限制。入站时立刻下载落盘，之后历史展示和喂给模型都用本地副本。
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 20 * 1024 * 1024
DOWNLOAD_TIMEOUT = 20.0
PUBLIC_PREFIX = "/api/v1/robots/images/"
LEGACY_PUBLIC_PREFIX = "/robots/images/"
# 入站图片只服务"近期历史展示 + 喂给模型"，超过 TTL 的缓存自动清除，
# 存储不随时间膨胀。
IMAGE_TTL_SECONDS = 24 * 3600

_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}


def _store_dir() -> Path:
    home = os.environ.get("TERMPAWS_HOME", str(Path.home() / ".termpaws"))
    path = Path(home) / "robot_images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def image_file_path(name: str) -> Path | None:
    """公开路径名 -> 本地文件；非法名字（穿越）返回 None。"""
    clean = Path(str(name or "")).name
    if not clean or clean.startswith("."):
        return None
    path = _store_dir() / clean
    return path if path.exists() else None


def public_image_path(name: str) -> str:
    return f"{PUBLIC_PREFIX}{name}"


def _sweep_expired_images() -> None:
    """删除超过 TTL 的缓存图片（在每次新图落盘时顺带执行，零后台任务）。"""
    try:
        cutoff = time.time() - IMAGE_TTL_SECONDS
        removed = 0
        for path in _store_dir().iterdir():
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                pass
        if removed:
            logger.info("[RobotImageStore] 清理过期图片 %d 张", removed)
    except Exception:
        pass


def store_image_from_url(url: str) -> str | None:
    """下载图片落盘，返回图片名（用于 public_image_path）。失败返回 None。"""
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    _sweep_expired_images()
    try:
        with httpx.Client(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
        payload = response.content
        if not payload or len(payload) > MAX_IMAGE_BYTES:
            logger.warning(
                "[RobotImageStore] 图片为空或过大 (%d bytes): %s", len(payload), url[:80]
            )
            return None
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        ext = _EXT_BY_MIME.get(content_type)
        if ext is None:
            # NTQQ 有时不给 content-type；用魔数兜底
            if payload[:3] == b"\xff\xd8\xff":
                ext = ".jpg"
            elif payload[:8] == b"\x89PNG\r\n\x1a\n":
                ext = ".png"
            elif payload[:6] in (b"GIF87a", b"GIF89a"):
                ext = ".gif"
            elif payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
                ext = ".webp"
            else:
                logger.warning(
                    "[RobotImageStore] 无法识别图片格式: %s (%s)", url[:80], content_type
                )
                return None
        name = f"{uuid.uuid4().hex}{ext}"
        path = _store_dir() / name
        path.write_bytes(payload)
        return name
    except Exception as exc:
        logger.warning("[RobotImageStore] 图片下载失败 %s: %s", url[:80], exc)
        return None
