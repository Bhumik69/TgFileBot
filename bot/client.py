"""
Pyrogram client creation and handler registration.
"""

from pyrogram import Client

from config import config
from bot.handlers import register_handlers

async def create_client() -> Client:
    app = Client(
        name="filebot",
        api_id=config.api_id,
        api_hash=config.api_hash,
        bot_token=config.bot_token,
        # Render's filesystem is ephemeral. Authenticate from the bot token on
        # every start instead of creating or requiring filebot.session.
        in_memory=True,
    )
    register_handlers(app)
    return app
