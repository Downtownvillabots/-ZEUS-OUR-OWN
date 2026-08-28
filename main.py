"""
NEW TELEGRAM BOT
File 1: main.py

Purpose:
    Application entry point for the new bot.

Design rules:
    - The new bot is independent from the old/reference bot.
    - Configuration comes from environment variables.
    - Feature modules are loaded through the plugin package.
    - Startup/shutdown is centralized here.
    - No database, search, admin, backup, or media logic belongs here.

Required environment variables for the first startup test:
    API_ID=123456
    API_HASH=your_api_hash
    BOT_TOKEN=your_bot_token

Optional:
    SESSION_NAME=new_telegram_bot
    PLUGINS_PACKAGE=plugins
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Basic project paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").strip().upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.INFO)

logging.basicConfig(
    level=LOG_LEVEL,
    format=(
        "%(asctime)s | %(levelname)-8s | "
        "%(name)s | %(message)s"
    ),
    datefmt="%Y-%m-%d %H:%M:%S",
)

LOGGER = logging.getLogger("new_bot")


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def _required_env(name: str) -> str:
    """Return a required environment variable or fail clearly."""
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not configured."
        )

    return value


def _positive_int_env(name: str, default: int | None = None) -> int:
    """Read a positive integer environment variable safely."""
    raw = os.getenv(name, "").strip()

    if not raw:
        if default is not None:
            return default
        raise RuntimeError(
            f"Required environment variable '{name}' is not configured."
        )

    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Environment variable '{name}' must be an integer."
        ) from exc

    if value <= 0:
        raise RuntimeError(
            f"Environment variable '{name}' must be greater than zero."
        )

    return value


def _parse_plugin_modules(package_name: str) -> list[str]:
    """
    Read optional plugin module names.

    PLUGINS can be:
        plugins.start,plugins.help

    If PLUGINS is empty, the package itself is loaded when possible.
    """
    raw = os.getenv("PLUGINS", "").strip()

    if not raw:
        return []

    modules: list[str] = []

    for item in raw.replace(";", ",").split(","):
        module = item.strip()

        if module and module not in modules:
            modules.append(module)

    return modules


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_ID = _positive_int_env("API_ID")
API_HASH = _required_env("API_HASH")
BOT_TOKEN = _required_env("BOT_TOKEN")

SESSION_NAME = (
    os.getenv("SESSION_NAME", "new_telegram_bot").strip()
    or "new_telegram_bot"
)

PLUGINS_PACKAGE = (
    os.getenv("PLUGINS_PACKAGE", "plugins").strip()
    or "plugins"
)

EXPLICIT_PLUGINS = _parse_plugin_modules(PLUGINS_PACKAGE)


# ---------------------------------------------------------------------------
# Telegram client
# ---------------------------------------------------------------------------

try:
    from pyrogram import Client
except ImportError as exc:
    raise RuntimeError(
        "Pyrogram is not installed. Install the project's requirements "
        "before starting the bot."
    ) from exc


class NewTelegramBot:
    """
    Application controller.

    Keeping lifecycle logic in one small object gives later features a
    stable startup/shutdown integration point without turning main.py
    into a giant feature file.
    """

    def __init__(self) -> None:
        self.client = Client(
            name=SESSION_NAME,
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workdir=str(BASE_DIR),
        )

        self._stop_event = asyncio.Event()
        self._shutdown_requested = False

    # ------------------------------------------------------------------
    # Plugin loading
    # ------------------------------------------------------------------

    @staticmethod
    def _module_exists(module_name: str) -> bool:
        try:
            importlib.util.find_spec(module_name)
            return True
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def _discover_package_plugins(self) -> list[str]:
        """
        Discover .py modules inside the configured plugin package.

        Files beginning with '_' are ignored.

        The package can remain empty during early development, which lets
        us test the application bootstrap before adding feature modules.
        """
        package_path = BASE_DIR / PLUGINS_PACKAGE.replace(".", "/")

        if not package_path.is_dir():
            LOGGER.info(
                "Plugin directory '%s' does not exist yet; "
                "continuing without plugins.",
                package_path,
            )
            return []

        modules: list[str] = []

        for file_path in sorted(package_path.glob("*.py")):
            if file_path.name.startswith("_"):
                continue

            module_name = f"{PLUGINS_PACKAGE}.{file_path.stem}"

            if module_name not in modules:
                modules.append(module_name)

        return modules

    def load_plugins(self) -> None:
        """
        Import feature modules once.

        Explicit PLUGINS takes priority. If it is not configured, every
        normal Python module in the plugins directory is discovered.
        """
        if EXPLICIT_PLUGINS:
            modules = EXPLICIT_PLUGINS
        else:
            modules = self._discover_package_plugins()

        if not modules:
            LOGGER.info("No plugins loaded yet.")
            return

        loaded = 0

        for module_name in modules:
            if not self._module_exists(module_name):
                raise RuntimeError(
                    f"Configured plugin '{module_name}' was not found."
                )

            try:
                importlib.import_module(module_name)
                loaded += 1
                LOGGER.info("Loaded plugin: %s", module_name)
            except Exception:
                LOGGER.exception(
                    "Failed to load plugin: %s",
                    module_name,
                )
                raise

        LOGGER.info(
            "Plugin loading complete: %d module(s).",
            loaded,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize plugins and start the Telegram client."""
        LOGGER.info("Starting new Telegram bot...")
        LOGGER.info("Session: %s", SESSION_NAME)

        self.load_plugins()

        await self.client.start()

        me = await self.client.get_me()

        username = (
            f"@{me.username}"
            if getattr(me, "username", None)
            else "no username"
        )

        LOGGER.info(
            "Bot connected: %s (%s)",
            username,
            getattr(me, "id", "unknown"),
        )

        LOGGER.info("New Telegram bot is ONLINE.")

    async def stop(self) -> None:
        """Stop the Telegram client exactly once."""
        if self._shutdown_requested:
            return

        self._shutdown_requested = True
        LOGGER.info("Stopping new Telegram bot...")

        try:
            await self.client.stop()
        except Exception:
            LOGGER.exception("Error while stopping Telegram client.")

        self._stop_event.set()
        LOGGER.info("New Telegram bot stopped.")

    async def run(self) -> None:
        """Run until a shutdown signal or an unrecoverable error."""
        await self.start()

        try:
            await self._stop_event.wait()
        except asyncio.CancelledError:
            LOGGER.info("Main task cancelled.")
            raise
        finally:
            await self.stop()


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

def _install_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    bot: NewTelegramBot,
) -> None:
    """
    Register SIGINT/SIGTERM where the operating system supports it.

    Some hosting environments do not expose normal signal handling, so
    failure to register a handler is intentionally non-fatal.
    """

    def request_shutdown() -> None:
        if bot._shutdown_requested:
            return

        LOGGER.info("Shutdown signal received.")
        bot._stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, request_shutdown)
        except (NotImplementedError, RuntimeError, OSError):
            LOGGER.debug(
                "Signal handler unavailable for %s.",
                signum,
            )


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Synchronous process entry point.

    Keeping asyncio.run() here means all asynchronous lifecycle handling
    remains inside NewTelegramBot.
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        bot = NewTelegramBot()
        _install_signal_handlers(loop, bot)

        loop.run_until_complete(bot.run())

    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt received.")

    except Exception:
        LOGGER.exception("Fatal bot startup/runtime error.")
        raise

    finally:
        try:
            loop.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
