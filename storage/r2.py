"""
Cloudflare R2 client – streaming multipart upload with retry logic.

R2 is S3-compatible, so we use boto3 with a custom endpoint.

Key design choices
──────────────────
• Files < MULTIPART_THRESHOLD  → single PutObject call (still streamed via
  an in-memory pipe so RAM stays bounded by CHUNK_SIZE, not file size).
• Files ≥ MULTIPART_THRESHOLD  → S3 multipart upload (5 MB minimum part size
  is enforced by AWS/R2).
• All network I/O is performed in a thread-pool executor so it doesn't
  block the asyncio event loop.
• Exponential-backoff retry on transient errors.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import time
from typing import AsyncIterator, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from config import config

logger = logging.getLogger(__name__)

_PART_SIZE = max(config.multipart_chunksize, 5 * 1024 * 1024)   # R2 min = 5 MB
_THRESHOLD = config.multipart_threshold
_MAX_RETRIES = config.max_retries


def _make_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{config.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=config.r2_access_key_id,
        aws_secret_access_key=config.r2_secret_access_key,
        region_name="auto",
        config=BotoConfig(
            retries={"max_attempts": 1, "mode": "standard"},  # We do our own retry
            max_pool_connections=10,
        ),
    )


class R2Client:
    """Async-friendly wrapper around boto3 S3 calls."""

    def __init__(self):
        self._s3 = _make_s3_client()
        self._loop = asyncio.get_event_loop()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upload_stream(
        self,
        stream: AsyncIterator[bytes],
        object_key: str,
        content_type: str,
        file_size: int,
        sha256_accumulator: "hashlib._Hash",
    ) -> str:
        """
        Consume the async byte stream and upload to R2.
        Returns the hex SHA-256 digest of the uploaded data.
        """
        if file_size and file_size < _THRESHOLD:
            await self._single_upload(stream, object_key, content_type, sha256_accumulator)
        else:
            await self._multipart_upload(stream, object_key, content_type, sha256_accumulator)

        return sha256_accumulator.hexdigest()

    async def delete_object(self, object_key: str) -> None:
        """Delete an object from R2 (used to clean up duplicates)."""
        await self._run_sync(self._s3.delete_object, Bucket=config.r2_bucket_name, Key=object_key)

    def public_url(self, object_key: str) -> str:
        return f"{config.r2_public_url}/{object_key}"

    # ------------------------------------------------------------------
    # Single upload (< threshold)
    # ------------------------------------------------------------------

    async def _single_upload(
        self,
        stream: AsyncIterator[bytes],
        object_key: str,
        content_type: str,
        sha256: "hashlib._Hash",
    ) -> None:
        """Buffer stream into a BytesIO then PutObject (fine for small files)."""
        buf = io.BytesIO()
        async for chunk in stream:
            sha256.update(chunk)
            buf.write(chunk)

        buf.seek(0)
        size = buf.tell()
        buf.seek(0)

        await self._retry(
            self._s3.put_object,
            Bucket=config.r2_bucket_name,
            Key=object_key,
            Body=buf,
            ContentType=content_type,
            ContentLength=size,
        )
        logger.debug("Single upload complete: %s", object_key)

    # ------------------------------------------------------------------
    # Multipart upload (≥ threshold)
    # ------------------------------------------------------------------

    async def _multipart_upload(
        self,
        stream: AsyncIterator[bytes],
        object_key: str,
        content_type: str,
        sha256: "hashlib._Hash",
    ) -> None:
        upload_id: Optional[str] = None
        parts: list[dict] = []
        part_number = 1

        try:
            resp = await self._retry(
                self._s3.create_multipart_upload,
                Bucket=config.r2_bucket_name,
                Key=object_key,
                ContentType=content_type,
            )
            upload_id = resp["UploadId"]
            logger.debug("Multipart upload created upload_id=%s", upload_id)

            part_buf = io.BytesIO()
            part_buf_size = 0

            async for chunk in stream:
                sha256.update(chunk)
                part_buf.write(chunk)
                part_buf_size += len(chunk)

                while part_buf_size >= _PART_SIZE:
                    # Flush one part
                    part_buf.seek(0)
                    part_data = part_buf.read(_PART_SIZE)
                    remaining = part_buf.read()  # bytes after the part boundary

                    etag = await self._upload_part(object_key, upload_id, part_number, part_data)
                    parts.append({"PartNumber": part_number, "ETag": etag})
                    logger.debug("Uploaded part %d (%d bytes)", part_number, len(part_data))
                    part_number += 1

                    # Reset buffer with the remainder
                    part_buf = io.BytesIO()
                    part_buf.write(remaining)
                    part_buf_size = len(remaining)

            # Upload final (possibly partial) part
            if part_buf_size > 0:
                part_buf.seek(0)
                part_data = part_buf.read()
                etag = await self._upload_part(object_key, upload_id, part_number, part_data)
                parts.append({"PartNumber": part_number, "ETag": etag})
                logger.debug("Uploaded final part %d (%d bytes)", part_number, len(part_data))

            # Complete
            await self._retry(
                self._s3.complete_multipart_upload,
                Bucket=config.r2_bucket_name,
                Key=object_key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
            logger.debug("Multipart upload complete: %s (%d parts)", object_key, len(parts))

        except Exception:
            if upload_id:
                try:
                    await self._run_sync(
                        self._s3.abort_multipart_upload,
                        Bucket=config.r2_bucket_name,
                        Key=object_key,
                        UploadId=upload_id,
                    )
                    logger.warning("Aborted multipart upload_id=%s", upload_id)
                except Exception as abort_err:
                    logger.error("Failed to abort multipart upload: %s", abort_err)
            raise

    async def _upload_part(
        self, object_key: str, upload_id: str, part_number: int, data: bytes
    ) -> str:
        resp = await self._retry(
            self._s3.upload_part,
            Bucket=config.r2_bucket_name,
            Key=object_key,
            UploadId=upload_id,
            PartNumber=part_number,
            Body=data,
        )
        return resp["ETag"]

    # ------------------------------------------------------------------
    # Retry helper
    # ------------------------------------------------------------------

    async def _retry(self, func, **kwargs):
        """Run a boto3 call in a thread with exponential-backoff retry."""
        delay = 1.0
        last_exc = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return await self._run_sync(func, **kwargs)
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                # Don't retry on permanent errors
                if code in ("NoSuchBucket", "AccessDenied", "InvalidAccessKeyId"):
                    raise
                last_exc = exc
                logger.warning("Attempt %d/%d failed (%s), retrying in %.1fs…", attempt, _MAX_RETRIES, code, delay)
            except Exception as exc:
                last_exc = exc
                logger.warning("Attempt %d/%d failed (%s), retrying in %.1fs…", attempt, _MAX_RETRIES, exc, delay)

            if attempt < _MAX_RETRIES:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)

        raise RuntimeError(f"All {_MAX_RETRIES} upload attempts failed") from last_exc

    async def _run_sync(self, func, **kwargs):
        """Execute a blocking boto3 call in the default thread-pool executor."""
        return await self._loop.run_in_executor(None, lambda: func(**kwargs))
