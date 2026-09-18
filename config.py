"""
Configuration loaded from environment variables / .env file
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    # Telegram
    api_id: int
    api_hash: str
    bot_token: str

    # Cloudflare R2
    r2_account_id: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket_name: str
    r2_public_url: str          # e.g. https://pub-xxx.r2.dev  OR custom domain

    # Upload tuning
    chunk_size: int             # bytes per streaming chunk
    multipart_threshold: int    # files above this use multipart
    multipart_chunksize: int    # size of each multipart part (min 5 MB)
    max_retries: int

    # SQLite
    db_path: str

    @classmethod
    def from_env(cls) -> "Config":
        def req(key: str) -> str:
            val = os.getenv(key)
            if not val:
                raise RuntimeError(f"Missing required env var: {key}")
            return val

        return cls(
            api_id=int(req("TELEGRAM_API_ID")),
            api_hash=req("TELEGRAM_API_HASH"),
            bot_token=req("TELEGRAM_BOT_TOKEN"),
            r2_account_id=req("R2_ACCOUNT_ID"),
            r2_access_key_id=req("R2_ACCESS_KEY_ID"),
            r2_secret_access_key=req("R2_SECRET_ACCESS_KEY"),
            r2_bucket_name=req("R2_BUCKET_NAME"),
            r2_public_url=req("R2_PUBLIC_URL").rstrip("/"),
            chunk_size=int(os.getenv("CHUNK_SIZE", str(512 * 1024))),          # 512 KB
            multipart_threshold=int(os.getenv("MULTIPART_THRESHOLD", str(50 * 1024 * 1024))),   # 50 MB
            multipart_chunksize=int(os.getenv("MULTIPART_CHUNKSIZE", str(50 * 1024 * 1024))),   # 50 MB
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            db_path=os.getenv("DB_PATH", "filebot.db"),
        )


config = Config.from_env()
