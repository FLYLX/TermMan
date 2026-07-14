import asyncio

from app.services.agent.turn_coordinator import AgentTurnCoordinator, agent_turn_key


def test_agent_turn_coordinator_serializes_async_waiters_in_fifo_order() -> None:
    async def scenario() -> list[str]:
        coordinator = AgentTurnCoordinator()
        key = agent_turn_key("handler-1")
        first = coordinator.acquire(key)
        order: list[str] = []

        async def worker(name: str) -> None:
            lease = await coordinator.acquire_async(key)
            try:
                order.append(name)
                await asyncio.sleep(0.02)
            finally:
                lease.release()

        worker_a = asyncio.create_task(worker("qq"))
        await asyncio.sleep(0.03)
        worker_b = asyncio.create_task(worker("web"))
        await asyncio.sleep(0.03)

        assert order == []
        first.release()
        await asyncio.gather(worker_a, worker_b)
        return order

    assert asyncio.run(scenario()) == ["qq", "web"]


def test_agent_turn_coordinator_does_not_block_different_handlers() -> None:
    coordinator = AgentTurnCoordinator()
    first = coordinator.acquire(agent_turn_key("handler-1"))
    second = coordinator.acquire(agent_turn_key("handler-2"))

    second.release()
    first.release()
