import logging

from sqlmodel import Session, select

from app.core.db import engine
from app.models import Item, ItemHandlerItem

logger = logging.getLogger(__name__)


class AgentInputBridge:
    """
    Convert terminal stream payloads into agent session input.

    Responsibilities:
    - resolve which handler is attached to an item
    - load item filter configuration
    - pass raw + filtered terminal output into stream_manager
    """

    def handle_stream(self, item_uuid: str, data: dict[str, object]) -> None:
        if data.get("source") == "job":
            logger.debug("[AgentInputBridge] Skipping daemon job stream for item %s", item_uuid)
            return
        logger.info(
            "[AgentInputBridge] handle_stream: item=%s stdout_len=%s stderr_len=%s",
            item_uuid,
            len(str(data.get("stdout") or "")),
            len(str(data.get("stderr") or "")),
        )
        try:
            from app.services.agent import item_handler_context
            from app.services.agent.stream_manager import stream_manager

            raw_output = self._build_raw_output(data)
            if not raw_output.strip():
                return

            item = self._load_item(item_uuid)
            filtered_output = self._build_filtered_output(item, data, raw_output)

            handler_id = item_handler_context.get_handler(item_uuid) or self._load_handler_id(item_uuid)
            if not handler_id:
                logger.debug("[AgentInputBridge] No handler found for item %s", item_uuid)
                return

            stream_manager.process_stream(
                item_uuid,
                filtered_output,
                handler_id,
                raw_output=raw_output,
            )
            logger.debug(
                "[AgentInputBridge] Processed stream for item=%s, handler=%s, output_len=%s",
                item_uuid,
                handler_id,
                len(filtered_output),
            )
        except Exception as exc:
            logger.error("[AgentInputBridge] Failed to bridge stream for item %s: %s", item_uuid, exc, exc_info=True)

    def _load_handler_id(self, item_uuid: str) -> str | None:
        with Session(engine) as session:
            handler_item = session.exec(
                select(ItemHandlerItem).where(ItemHandlerItem.item_id == item_uuid)
            ).first()
            if handler_item:
                return str(handler_item.item_handler_id)
        return None

    def _load_item(self, item_uuid: str) -> Item | None:
        with Session(engine) as session:
            return session.exec(
                select(Item).where(Item.id == item_uuid)
            ).first()

    def _build_raw_output(self, data: dict[str, object]) -> str:
        stdout = data.get("stdout", "")
        stderr = data.get("stderr", "")
        return f"{stdout}{stderr}"

    def _build_filtered_output(
        self,
        item: Item | None,
        data: dict[str, object],
        raw_output: str,
    ) -> str:
        if not item or not item.input_filter_enabled:
            return raw_output

        try:
            from app.services.filters.input_filter import InputFilter, InputFilterConfig

            config = InputFilterConfig.from_item(item)
            input_filter = InputFilter(config)
            event = input_filter.filter(data)
            return event.raw_content if event else ""
        except Exception as exc:
            logger.debug("[AgentInputBridge] Filter error for item %s: %s", item.id, exc)
            return raw_output
