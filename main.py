"""
Telegram File Link Generator Bot
Entry point
"""

import asyncio
import logging
import os
import sys

from bot.client import create_client
from database.db import init_db
from utils.logger import setup_logging


async def handle_health_check(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    """Serve a minimal HTTP response for Render's web-service health checks."""
    try:
        await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        body = b"Telegram bot is running\n"
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + body
        )
        await writer.drain()
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    port = int(os.getenv("PORT", "10000"))
    health_server = await asyncio.start_server(
        handle_health_check, host="0.0.0.0", port=port
    )
    logger.info("Health server listening on 0.0.0.0:%d", port)

    logger.info("Initializing database...")
    await init_db()

    logger.info("Starting Telegram bot...")
    app = await create_client()

    try:
        await app.start()
        logger.info("Bot is running. Press Ctrl+C to stop.")
        await asyncio.Event().wait()

    except asyncio.CancelledError:
        logger.info("Shutdown requested...")
        raise

    finally:
        try:
            if app.is_connected:
                await app.stop()
        except ConnectionError:
            logger.debug("Pyrogram client was already terminated.")
        health_server.close()
        await health_server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
