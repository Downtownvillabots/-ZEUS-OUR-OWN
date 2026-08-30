"""
Integration-layer tests.

These tests verify the composition infrastructure without starting
Telegram polling or requiring real PostgreSQL/Redis connections.
"""

from __future__ import annotations

import pytest

from bot.integration.handler_registry import (
    HandlerRegistry,
)

from bot.integration.middleware_registry import (
    MiddlewareRegistry,
)

from bot.integration.service_registry import (
    ServiceRegistry,
)

from bot.integration.wiring import (
    ApplicationWiring,
)


class FakeService:

    async def initialize(self):
        self.initialized = True

    async def shutdown(self):
        self.initialized = False

    async def health(self):
        return {
            "healthy": True,
            "status": "ok",
        }


class FakeApplication:

    def __init__(self):
        self.handlers = []
        self.error_handlers = []

    def add_handler(
        self,
        handler,
        group=0,
    ):
        self.handlers.append(
            (
                group,
                handler,
            )
        )

    def add_error_handler(
        self,
        handler,
    ):
        self.error_handlers.append(
            handler
        )


def test_service_registry_registers_service():

    registry = ServiceRegistry()

    service = FakeService()

    registry.register(
        "test",
        service,
    )

    assert registry.contains(
        "test"
    )

    assert registry.get(
        "test"
    ) is service


def test_service_registry_rejects_duplicates():

    registry = ServiceRegistry()

    registry.register(
        "test",
        FakeService(),
    )

    with pytest.raises(
        ValueError
    ):

        registry.register(
            "test",
            FakeService(),
        )


@pytest.mark.asyncio
async def test_service_registry_initializes():

    registry = ServiceRegistry()

    service = FakeService()

    registry.register(
        "test",
        service,
        required=True,
    )

    await registry.initialize()

    entry = registry.entry(
        "test"
    )

    assert entry.initialized is True

    assert entry.healthy is True


@pytest.mark.asyncio
async def test_service_registry_shutdown():

    registry = ServiceRegistry()

    service = FakeService()

    registry.register(
        "test",
        service,
        required=True,
    )

    await registry.initialize()

    await registry.shutdown()

    entry = registry.entry(
        "test"
    )

    assert entry.initialized is False


def test_service_dependencies_are_ordered():

    registry = ServiceRegistry()

    database = FakeService()

    search = FakeService()

    registry.register(
        "database",
        database,
        priority=20,
    )

    registry.register(
        "search",
        search,
        priority=10,
        dependencies=(
            "database",
        ),
    )

    ordered = registry.dependency_order()

    names = [
        entry.name
        for entry in ordered
    ]

    assert names.index(
        "database"
    ) < names.index(
        "search"
    )


def test_handler_registry_registers():

    registry = HandlerRegistry()

    handler = object()

    registry.register(
        "start",
        handler,
    )

    assert registry.get(
        "start"
    ) is handler


def test_handler_registry_orders_handlers():

    registry = HandlerRegistry()

    first = object()

    second = object()

    registry.register(
        "second",
        second,
        group=10,
        priority=20,
    )

    registry.register(
        "first",
        first,
        group=0,
        priority=10,
    )

    entries = registry.entries()

    assert entries[0].name == "first"

    assert entries[1].name == "second"


def test_handler_registry_installs():

    registry = HandlerRegistry()

    handler = object()

    registry.register(
        "start",
        handler,
    )

    application = FakeApplication()

    count = registry.register_all(
        application
    )

    assert count == 1

    assert len(
        application.handlers
    ) == 1


def test_middleware_registry_registers():

    registry = MiddlewareRegistry()

    middleware = object()

    registry.register(
        "auth",
        middleware,
    )

    assert registry.get(
        "auth"
    ) is middleware


def test_middleware_registry_orders():

    registry = MiddlewareRegistry()

    low = object()

    high = object()

    registry.register(
        "high",
        high,
        priority=100,
    )

    registry.register(
        "low",
        low,
        priority=10,
    )

    entries = registry.entries()

    assert entries[0].name == "low"

    assert entries[1].name == "high"


def test_wiring_constructs_registries(
    fake_settings,
):

    wiring = ApplicationWiring(
        fake_settings
    )

    assert wiring.services is not None

    assert wiring.handlers is not None

    assert wiring.middleware is not None


def test_wiring_summary(
    fake_settings,
):

    wiring = ApplicationWiring(
        fake_settings
    )

    summary = wiring.summary()

    assert "state" in summary

    assert "services" in summary

    assert "middleware" in summary

    assert "handlers" in summary


def test_wiring_validation_accepts_basic_settings(
    fake_settings,
):

    wiring = ApplicationWiring(
        fake_settings
    )

    errors = wiring.validate()

    assert errors == []


@pytest.mark.asyncio
async def test_service_health():

    registry = ServiceRegistry()

    registry.register(
        "test",
        FakeService(),
        required=True,
    )

    await registry.initialize()

    result = await registry.health()

    assert result["healthy"] is True

    assert (
        result["services"]["test"]["healthy"]
        is True
    )