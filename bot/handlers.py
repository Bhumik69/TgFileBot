import logging

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from bot.pipeline import active_uploads, process_file, stopped_uploads
from config import config
from database.db import delete_file_by_slug, get_file_by_slug
from utils.formatting import human_size

logger = logging.getLogger(__name__)

MEDIA_FILTER = (
    filters.document
    | filters.video
    | filters.audio
    | filters.photo
    | filters.animation
    | filters.voice
    | filters.video_note
)

HELP_TEXT = """
Available commands:

/start
Start the bot and show a short welcome message.

/help
Show this command list.

/status
Check whether you currently have an upload running.

/stop
Stop your current upload. The incomplete upload is discarded.

/cancel
Same as /stop.

/resume
Start your last stopped file again from the beginning.

How to upload:
Send or forward a document, video, audio, photo, GIF, voice message, or video note.

Note:
/resume does not continue from the exact byte where /stop was used. It restarts the last stopped Telegram file because this bot streams directly from Telegram to R2.
""".strip()


def register_handlers(app: Client) -> None:

    @app.on_message(filters.command("start"))
    async def on_start(client: Client, message: Message) -> None:
        name = message.from_user.first_name if message.from_user else "there"
        await message.reply_text(
            f"Hey {name}!\n\n"
            "Bot is up and running.\n\n"
            "Send or forward me any supported file and I will upload it to R2 "
            "and reply with a permanent download link.\n\n"
            "Use /help to see all commands."
        )

    @app.on_message(filters.command("help"))
    async def on_help(client: Client, message: Message) -> None:
        await message.reply_text(HELP_TEXT)

    @app.on_message(MEDIA_FILTER & ~filters.bot)
    async def on_media(client: Client, message: Message) -> None:
        logger.info(
            "Received media from user=%s chat=%s",
            message.from_user.id if message.from_user else "?",
            message.chat.id,
        )
        await process_file(client, message)

    @app.on_message(filters.command(["cancel", "stop"]))
    async def on_stop(client: Client, message: Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        state = active_uploads.get(user_id)
        if state:
            state.cancel_event.set()
            await message.reply_text(
                "Stopping your upload...\n"
                "Use /resume after it stops to start the same file again."
            )
        else:
            await message.reply_text("No active upload to stop.")

    @app.on_message(filters.command("resume"))
    async def on_resume(client: Client, message: Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        if user_id in active_uploads:
            await message.reply_text("An upload is already running. Use /status to check it.")
            return

        stopped_message = stopped_uploads.get(user_id)
        if not stopped_message:
            await message.reply_text("No stopped upload found. Send a file first, then use /stop if needed.")
            return

        await message.reply_text("Resuming your last stopped file from the beginning...")
        await process_file(client, stopped_message)

    @app.on_message(filters.command("status"))
    async def on_status(client: Client, message: Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        if user_id in active_uploads:
            await message.reply_text("Upload is currently in progress.\nSend /stop to stop it.")
        elif user_id in stopped_uploads:
            await message.reply_text("No upload is running. Send /resume to restart your last stopped file.")
        else:
            await message.reply_text("No active upload.")

    @app.on_callback_query()
    async def on_callback(client: Client, query: CallbackQuery) -> None:
        data = query.data or ""

        if data.startswith("refresh:"):
            slug = data.split(":", 1)[1]
            file = await get_file_by_slug(slug)
            if not file:
                await query.answer("File not found.", show_alert=True)
                return

            url = f"{config.r2_public_url}/{file['object_key']}"
            await query.message.edit_text(
                f"Uploaded Successfully\n\n"
                f"File Name: `{file['file_name']}`\n"
                f"File Size: {human_size(file['file_size'])}\n"
                f"Download Link: {url}\n\n"
                "Last refreshed just now",
                reply_markup=query.message.reply_markup,
            )
            await query.answer("Refreshed!")

        elif data.startswith("delete:"):
            slug = data.split(":", 1)[1]
            file = await get_file_by_slug(slug)
            if not file:
                await query.answer("Already deleted.", show_alert=True)
                return

            from storage.r2 import R2Client

            r2 = R2Client()
            await r2.delete_object(file["object_key"])
            await delete_file_by_slug(slug)
            await query.message.edit_text("File deleted from R2 and database.")
            await query.answer("Deleted.")
