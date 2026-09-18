"""
Telegram File Link Generator Bot
Entry point
"""

import asyncio
import logging
import sys

from bot.client import create_client
from database.db import init_db
from utils.logger import setup_logging


async def main():
    setup_logging()
    logger = logging.getLogger(__name__)

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


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
