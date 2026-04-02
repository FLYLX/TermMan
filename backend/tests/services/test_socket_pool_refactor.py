from app.services.socket_pool.agent_bridge import AgentInputBridge
from app.services.socket_pool.event_bus import (
    ItemEventBus,
    SubscriptionEventType,
)
from app.services.socket_pool.subscription_center import ItemSubscriptionCenter
from app.services.socket_pool.terminal_stream_pipeline import TerminalStreamPipeline


def test_terminal_stream_pipeline_publishes_stream_events() -> None:
    bus = ItemEventBus()
    pipeline = TerminalStreamPipeline(bus)
    received: list[tuple[str, dict]] = []

    bus.subscribe(
        "item-1",
        lambda event: received.append((event.event_type.value, event.data)),
        subscriber_type="test",
        event_types=[SubscriptionEventType.STREAM],
    )

    delivered = pipeline.publish_stream("item-1", {"stdout": "hello\n"})

    assert delivered == 1
    assert received == [("stream", {"stdout": "hello\n"})]


def test_agent_input_bridge_builds_raw_output_and_calls_stream_manager(monkeypatch) -> None:
    bridge = AgentInputBridge()
    captured: list[tuple[str, str, str, str]] = []

    monkeypatch.setattr(bridge, "_load_handler_id", lambda item_uuid: "handler-1")
    monkeypatch.setattr(bridge, "_load_item", lambda item_uuid: None)
    monkeypatch.setattr(
        "app.services.agent.stream_manager.stream_manager.process_stream",
        lambda item_uuid, filtered_output, handler_id, raw_output="": captured.append(
            (item_uuid, filtered_output, handler_id, raw_output)
        ),
    )

    bridge.handle_stream("item-1", {"stdout": "out\n", "stderr": "err\n"})

    assert captured == [("item-1", "out\nerr\n", "handler-1", "out\nerr\n")]


def test_subscription_center_runs_agent_bridge_after_stream_pipeline(monkeypatch) -> None:
    center = ItemSubscriptionCenter()
    call_order: list[str] = []

    monkeypatch.setattr(
        center._stream_pipeline,
        "publish_stream",
        lambda item_uuid, data: call_order.append("pipeline") or 1,
    )
    monkeypatch.setattr(
        center,
        "_trigger_agent_handler",
        lambda item_uuid, data: call_order.append("bridge"),
    )

    delivered = center.publish_stream("item-1", {"stdout": "hello\n"})

    assert delivered == 1
    assert call_order == ["pipeline", "bridge"]
