"""
Helpers to extract a unified MediaInfo from any Pyrogram message type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pyrogram.types import Message


@dataclass
class MediaInfo:
    file_id: str
    file_unique_id: str
    file_name: str
    file_size: int          # bytes (0 if unknown, e.g. some photos)
    mime_type: str


def extract_media_info(message: Message) -> Optional[MediaInfo]:
    """Return a MediaInfo from the first media attribute found, or None."""

    # Priority order
    media = (
        message.document
        or message.video
        or message.audio
        or message.animation
        or message.voice
        or message.video_note
        or message.sticker
    )

    if media:
        file_name = getattr(media, "file_name", None) or _guess_name(message, media)
        return MediaInfo(
            file_id=media.file_id,
            file_unique_id=media.file_unique_id,
            file_name=file_name,
            file_size=getattr(media, "file_size", 0) or 0,
            mime_type=getattr(media, "mime_type", "application/octet-stream") or "application/octet-stream",
        )

    # Photo – largest size
    if message.photo:
        photo = message.photo  # already the largest size in Pyrogram
        return MediaInfo(
            file_id=photo.file_id,
            file_unique_id=photo.file_unique_id,
            file_name=f"photo_{photo.file_unique_id}.jpg",
            file_size=photo.file_size or 0,
            mime_type="image/jpeg",
        )

    return None


def _guess_name(message: Message, media) -> str:
    """Fallback filename when the media object has no file_name attribute."""
    ext_map = {
        "video/mp4": ".mp4",
        "audio/mpeg": ".mp3",
        "audio/ogg": ".ogg",
        "video/webm": ".webm",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
    }
    mime = getattr(media, "mime_type", "") or ""
    ext = ext_map.get(mime, "")
    uid = getattr(media, "file_unique_id", "file")
    return f"{uid}{ext}"
