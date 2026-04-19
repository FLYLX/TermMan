import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal

from litellm import completion

from app.models import ItemHandler

logger = logging.getLogger(__name__)

LlmHealthStatus = Literal["connected", "error", "not_configured"]


class LlmHealthService:
    CACHE_TTL_SECONDS = 45
    REQUEST_TIMEOUT_SECONDS = 8
    MAX_WORKERS = 4

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def _cache_key(self, item_handler: ItemHandler) -> str:
        updated_at = item_handler.updated_at.isoformat() if item_handler.updated_at else ""
        return f"{item_handler.id}:{updated_at}"

    def _build_result(
        self,
        *,
        item_handler: ItemHandler,
        status: LlmHealthStatus,
        reachable: bool,
        message: str | None,
        checked_at: datetime | None = None,
        cached: bool = False,
    ) -> dict[str, Any]:
        return {
            "item_handler_id": item_handler.id,
            "status": status,
            "reachable": reachable,
            "message": message,
            "checked_at": checked_at or datetime.now(timezone.utc),
            "cached": cached,
        }

    def _check_once(self, item_handler: ItemHandler) -> dict[str, Any]:
        if not item_handler.model:
            return self._build_result(
                item_handler=item_handler,
                status="not_configured",
                reachable=False,
                message="No model configured",
            )

        kwargs: dict[str, Any] = {
            "model": item_handler.model,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "stream": False,
            "timeout": self.REQUEST_TIMEOUT_SECONDS,
            "temperature": 0,
            "max_tokens": 1,
        }
        if item_handler.api_key:
            kwargs["api_key"] = item_handler.api_key
        if item_handler.api_url:
            kwargs["api_base"] = item_handler.api_url

        try:
            completion(**kwargs)
            return self._build_result(
                item_handler=item_handler,
                status="connected",
                reachable=True,
                message="LLM reachable",
            )
        except Exception as exc:
            logger.warning(
                "[LLMHealth] LLM check failed for item_handler=%s: %s",
                item_handler.id,
                exc,
            )
            return self._build_result(
                item_handler=item_handler,
                status="error",
                reachable=False,
                message=str(exc).strip() or exc.__class__.__name__,
            )

    def get_status(
        self,
        item_handler: ItemHandler,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        cache_key = self._cache_key(item_handler)
        now = time.time()

        if not force:
            with self._lock:
                cached = self._cache.get(cache_key)
            if cached and cached["expires_at"] > now:
                return {
                    **cached["result"],
                    "cached": True,
                }

        result = self._check_once(item_handler)
        with self._lock:
            self._cache[cache_key] = {
                "expires_at": now + self.CACHE_TTL_SECONDS,
                "result": result,
            }
        return result

    def get_statuses(
        self,
        item_handlers: list[ItemHandler],
        *,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        if not item_handlers:
            return []

        max_workers = min(len(item_handlers), self.MAX_WORKERS)
        if max_workers <= 1:
            return [self.get_status(item_handler, force=force) for item_handler in item_handlers]

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self.get_status, item_handler, force=force)
                for item_handler in item_handlers
            ]
            return [future.result() for future in futures]


llm_health_service = LlmHealthService()

