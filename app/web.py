"""
DOWNTOWN VILLA
Small health server for Render.

This is infrastructure only. It does not contain bot features.
"""

from __future__ import annotations

from aiohttp import web

from app.logging import get_logger
from app.runtime import Runtime


LOGGER = get_logger(__name__)


async def health(request: web.Request) -> web.Response:
    runtime: Runtime = request.app["runtime"]

    return web.json_response(
        {
            "status": "ok",
            "project": runtime.config.project_name,
            "telegram_connected": runtime.started,
        }
    )


async def start_health_server(runtime: Runtime) -> web.AppRunner:
    app = web.Application()
    app["runtime"] = runtime
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=runtime.config.port,
    )
    await site.start()

    LOGGER.info(
        "Health server listening on port %s.",
        runtime.config.port,
    )

    runtime.web_runner = runner
    return runner
