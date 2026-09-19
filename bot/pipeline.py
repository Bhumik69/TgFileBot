"""
Upload pipeline:
  1. Extract file metadata from Telegram message.
  2. Check duplicate metadata after upload.
  3. Stream file from Telegram to Cloudflare R2 using multipart upload.
  4. Store metadata in SQLite.
  5. Reply with download link.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator

from pyrogram import Client
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import config
from database.db import get_file_by_hash, save_file
from storage.r2 import R2Client
from utils.formatting import human_size
from utils.media import MediaInfo, extract_media_info

logger = logging.getLogger(__name__)


@dataclass
class UploadState:
    cancel_event: asyncio.Event
    message: Message


active_uploads: dict[int, UploadState] = {}
stopped_uploads: dict[int, Message] = {}

# How often to update the progress message, in seconds.
PROGRESS_INTERVAL = 3.0


async def _edit_status(status_msg: Message, text: str, **kwargs) -> None:
    """Edit a status message without aborting an upload on a duplicate update."""
    try:
        await status_msg.edit_text(text, **kwargs)
    except MessageNotModified:
        # Rounded progress values can produce the same text twice. Telegram
        # reports that as an error even though the desired status is present.
        logger.debug("Skipped unchanged status message")


async def process_file(client: Client, message: Message) -> None:
    info = extract_media_info(message)
    if info is None:
        return

    user_id = message.from_user.id if message.from_user else 0
    if user_id in active_uploads:
        await message.reply_text(
            "An upload is already running.\n"
            "Use /status to check it, or /stop to stop it first."
        )
        return

    cancel_event = asyncio.Event()
    state = UploadState(cancel_event=cancel_event, message=message)
    active_uploads[user_id] = state

    status_msg = await message.reply_text("Processing your file...", quote=True)

    try:
        await _run_pipeline(client, message, info, status_msg, cancel_event)
        stopped_uploads.pop(user_id, None)
    except asyncio.CancelledError:
        stopped_uploads[user_id] = message
        await _edit_status(
            status_msg,
            "Upload stopped.\n"
            "Send /resume to start this file again from the beginning."
        )
    except Exception as exc:
        logger.exception("Pipeline failed for file_id=%s", info.file_id)
        await _edit_status(status_msg, f"Upload failed: {exc}")
    finally:
        if active_uploads.get(user_id) is state:
            active_uploads.pop(user_id, None)


async def _run_pipeline(
    client: Client,
    message: Message,
    info: MediaInfo,
    status_msg,
    cancel_event: asyncio.Event,
) -> None:
    r2 = R2Client()

    await _edit_status(status_msg, "Checking for duplicates...")

    sha256 = hashlib.sha256()
    total_bytes = 0
    last_update = time.monotonic()
    start_time = time.monotonic()

    async def _hashing_stream() -> AsyncIterator[bytes]:
        nonlocal total_bytes, last_update
        async for chunk in _stream_telegram_file(client, info.file_id):
            if cancel_event.is_set():
                raise asyncio.CancelledError()

            sha256.update(chunk)
            total_bytes += len(chunk)
            now = time.monotonic()
            if now - last_update >= PROGRESS_INTERVAL:
                pct = (total_bytes / info.file_size * 100) if info.file_size else 0
                speed = total_bytes / max(now - start_time, 0.001)
                await _edit_status(
                    status_msg,
                    f"Uploading... {pct:.1f}%\n"
                    f"{human_size(total_bytes)} / {human_size(info.file_size)}\n"
                    f"Speed: {human_size(int(speed))}/s"
                )
                last_update = now
            yield chunk

    object_key = _make_object_key(info.file_name)
    content_type = mimetypes.guess_type(info.file_name)[0] or "application/octet-stream"

    await r2.upload_stream(
        stream=_hashing_stream(),
        object_key=object_key,
        content_type=content_type,
        file_size=info.file_size,
        sha256_accumulator=sha256,
    )

    file_hash_hex = sha256.hexdigest()

    existing = await get_file_by_hash(file_hash_hex)
    if existing:
        logger.info("Duplicate detected hash=%s", file_hash_hex)
        await r2.delete_object(object_key)
        object_key = existing["object_key"]
        url = f"{config.r2_public_url}/{object_key}"
        await _edit_status(
            status_msg,
            f"Already uploaded (duplicate detected)\n\n"
            f"File Name: `{info.file_name}`\n"
            f"File Size: {human_size(info.file_size)}\n"
            f"Download Link: {url}"
        )
        return

    public_slug = str(uuid.uuid4())
    url = f"{config.r2_public_url}/{object_key}"

    await save_file(
        file_name=info.file_name,
        file_size=info.file_size,
        sha256=file_hash_hex,
        object_key=object_key,
        public_slug=public_slug,
    )

    elapsed = time.monotonic() - start_time
    avg_speed = total_bytes / max(elapsed, 0.001)

    await _edit_status(
        status_msg,
        f"Uploaded Successfully\n\n"
        f"File Name: `{info.file_name}`\n"
        f"File Size: {human_size(info.file_size)}\n"
        f"Download Link: {url}\n\n"
        f"Uploaded in {elapsed:.1f}s at {human_size(int(avg_speed))}/s",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Refresh", callback_data=f"refresh:{public_slug}"),
                InlineKeyboardButton("Delete", callback_data=f"delete:{public_slug}"),
            ]
        ])
    )


async def _stream_telegram_file(client: Client, file_id: str) -> AsyncIterator[bytes]:
    async for chunk in client.stream_media(file_id):
        yield chunk


def _make_object_key(file_name: str) -> str:
    uid = uuid.uuid4().hex[:8]
    safe_name = file_name.replace(" ", "_")
    return f"uploads/{uid}/{safe_name}"
