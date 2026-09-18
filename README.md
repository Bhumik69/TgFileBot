# 📁 Telegram File Link Generator Bot

A Telegram bot that automatically receives files (documents, videos, audio, photos),
streams them directly to **Cloudflare R2**, and replies with a permanent public download link.

**No files are ever written to the local disk.** Only a tiny SQLite metadata record is stored.

---

## ✨ Features

| Feature | Details |
|---------|---------|
| Zero local storage | Files stream Telegram → R2 in memory |
| Multipart uploads | Handles files **> 2 GB** (R2 min part = 5 MB) |
| SHA-256 dedup | Duplicate files reuse the existing R2 object |
| Progress updates | Live upload % + speed in the chat |
| Retry logic | Exponential backoff on transient network errors |
| Async architecture | Built on Pyrogram + asyncio + aiosqlite |

---

## 🗂️ Project Structure

```
tg-filebot/
├── main.py                 # Entry point
├── config.py               # Env-var configuration
├── requirements.txt
├── .env.example
│
├── bot/
│   ├── __init__.py
│   ├── client.py           # Pyrogram client factory
│   ├── handlers.py         # Message handler registration
│   └── pipeline.py         # Upload pipeline (core logic)
│
├── database/
│   ├── __init__.py
│   ├── db.py               # Async SQLite CRUD
│   └── schema.sql          # Schema reference
│
├── storage/
│   ├── __init__.py
│   └── r2.py               # Cloudflare R2 streaming uploader
│
└── utils/
    ├── __init__.py
    ├── formatting.py       # human_size() helper
    ├── logger.py           # Logging setup
    └── media.py            # MediaInfo extractor
```

---

## 🚀 Quick Start

### 1. Prerequisites

- **Python 3.12+**
- A **Cloudflare R2** bucket with public access enabled
- A Telegram **Bot Token** (from [@BotFather](https://t.me/BotFather))
- Telegram **API ID** and **API Hash** (from [my.telegram.org](https://my.telegram.org/apps))

### 2. Clone & Install

```bash
git clone <your-repo>
cd tg-filebot

python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env and fill in all required values
```

#### Cloudflare R2 Setup

1. Go to **Cloudflare Dashboard → R2 → Create bucket**
2. Enable **Public Access** on the bucket (or use a custom domain)
3. Go to **R2 → Manage R2 API Tokens → Create API Token**
   - Permission: **Object Read & Write**
   - Copy the Access Key ID and Secret Access Key
4. Set `R2_PUBLIC_URL` to your bucket's public URL:
   - Default: `https://pub-XXXXXXXX.r2.dev`
   - Custom domain: `https://files.yourdomain.com`

### 4. Run

```bash
python main.py
```

You should see:
```
2024-06-15 12:00:00 [INFO] __main__: Initializing database...
2024-06-15 12:00:00 [INFO] database.db: Database initialised at filebot.db
2024-06-15 12:00:00 [INFO] __main__: Starting Telegram bot...
2024-06-15 12:00:01 [INFO] __main__: Bot is running. Press Ctrl+C to stop.
```

### 5. Docker (optional)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

```bash
docker build -t tg-filebot .
docker run -d --env-file .env --name tg-filebot tg-filebot
```

---

## 📖 Usage

Simply **send or forward** any of the following to the bot:

- 📄 Document
- 🎥 Video
- 🎵 Audio
- 🖼️ Photo
- 🎞️ Animation / GIF
- 🎤 Voice message
- 📹 Video note

The bot will respond:

```
✅ Uploaded Successfully

File Name: example.mp4
File Size: 1.2 GB
Download Link: https://pub-xxx.r2.dev/uploads/a1b2c3d4/example.mp4

Uploaded in 45.2s at 27.2 MB/s
```

---

## ⚙️ Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_API_ID` | ✅ | – | From my.telegram.org |
| `TELEGRAM_API_HASH` | ✅ | – | From my.telegram.org |
| `TELEGRAM_BOT_TOKEN` | ✅ | – | From @BotFather |
| `R2_ACCOUNT_ID` | ✅ | – | Cloudflare account ID |
| `R2_ACCESS_KEY_ID` | ✅ | – | R2 API token key ID |
| `R2_SECRET_ACCESS_KEY` | ✅ | – | R2 API token secret |
| `R2_BUCKET_NAME` | ✅ | – | R2 bucket name |
| `R2_PUBLIC_URL` | ✅ | – | Public base URL for files |
| `CHUNK_SIZE` | ❌ | 524288 (512 KB) | Stream chunk size in bytes |
| `MULTIPART_THRESHOLD` | ❌ | 52428800 (50 MB) | Use multipart above this size |
| `MULTIPART_CHUNKSIZE` | ❌ | 52428800 (50 MB) | Size of each multipart part |
| `MAX_RETRIES` | ❌ | 3 | Retry attempts on failure |
| `DB_PATH` | ❌ | filebot.db | SQLite database file path |

---

## 🗄️ Database Schema

```sql
CREATE TABLE files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name   TEXT    NOT NULL,
    file_size   INTEGER NOT NULL,
    sha256      TEXT    NOT NULL UNIQUE,   -- duplicate detection
    object_key  TEXT    NOT NULL,          -- R2 key
    public_slug TEXT    NOT NULL UNIQUE,   -- UUID for URLs
    uploaded_at TEXT    NOT NULL           -- ISO-8601 UTC
);
```

---

## 🔧 Architecture Notes

### Streaming Upload Flow

```
Telegram CDN
    │
    │  stream_media() – yields chunks (no temp file)
    ▼
pipeline.py
    │  SHA-256 computed on the fly while streaming
    │
    ▼
storage/r2.py
    │  Small files  → PutObject (buffered in RAM)
    │  Large files  → CreateMultipartUpload → UploadPart × N → CompleteMultipartUpload
    ▼
Cloudflare R2
```

### Duplicate Detection

SHA-256 is computed as data flows through the pipeline. Once the upload completes:
1. The hash is looked up in SQLite.
2. If found → the freshly uploaded object is **deleted from R2** and the existing URL is returned.
3. If not found → metadata is saved and the new URL is returned.

### Memory Usage

- Each chunk is `CHUNK_SIZE` bytes (default 512 KB) in RAM at a time.
- For multipart, one full part (`MULTIPART_CHUNKSIZE`, default 50 MB) is buffered before upload.
- Peak RAM ≈ `MULTIPART_CHUNKSIZE` + overhead, regardless of file size.

---

## 📝 License

MIT

---

## Commands

| Command | What it does | How to use it |
|---------|--------------|---------------|
| `/start` | Shows the welcome message and confirms the bot is running. | Send `/start` in the bot chat. |
| `/help` | Lists all available commands and explains how to use them. | Send `/help` in the bot chat. |
| `/status` | Shows whether you currently have an upload running. | Send `/status` while using the bot. |
| `/stop` | Stops your current upload. The incomplete upload is discarded. | Send `/stop` while an upload is running. |
| `/cancel` | Same behavior as `/stop`. | Send `/cancel` while an upload is running. |
| `/resume` | Starts your last stopped file again from the beginning. | First stop an upload with `/stop`, then send `/resume`. |

`/resume` is not a byte-level resume. The current pipeline streams directly
from Telegram to Cloudflare R2, so the bot restarts the last stopped Telegram
file from the beginning.
