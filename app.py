import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path

import uvicorn
import yt_dlp

from asgiref.wsgi import WsgiToAsgi
from flask import Flask, Response, request

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 10000))

COOKIE_FILE = "/etc/secrets/cookies.txt"


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL environment variable is missing")


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

flask_app = Flask(__name__)


@flask_app.get("/")
async def home():
    return "YouTube Audio Telegram Bot is running!"


@flask_app.get("/health")
async def health():
    return "OK"


YOUTUBE_REGEX = re.compile(
    r"(https?://)?(www\.)?"
    r"(youtube\.com/watch\?v=[\w-]+"
    r"|youtu\.be/[\w-]+"
    r"|youtube\.com/shorts/[\w-]+)",
    re.IGNORECASE,
)


def is_youtube_url(text: str) -> bool:
    return bool(YOUTUBE_REGEX.search(text))


def download_audio(url: str, output_dir: str):
    output_template = str(
        Path(output_dir) / "%(title).200s.%(ext)s"
    )

    ydl_options = {
        "format": "bestaudio/best",

        "noplaylist": True,

        "outtmpl": output_template,

        # YouTube authentication cookies
        "cookiefile": COOKIE_FILE,

        # YouTube + bgutil PO Token provider
        "extractor_args": {
            "youtube": {
                "player_client": [
                    "mweb",
                ],
            },
            "youtubepot-bgutilhttp": {
                "base_url": "http://127.0.0.1:4416",
            },
        },

        # Convert downloaded audio to MP3
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],

        # Temporary debugging
        "verbose": True,
        "quiet": False,
        "no_warnings": False,
    }

    logger.info("Starting download")

    with yt_dlp.YoutubeDL(ydl_options) as ydl:
        info = ydl.extract_info(
            url,
            download=True,
        )

        title = info.get(
            "title",
            "YouTube Audio",
        )

        downloaded_file = ydl.prepare_filename(info)

        mp3_file = str(
            Path(downloaded_file).with_suffix(".mp3")
        )

        logger.info(
            "Downloaded MP3: %s",
            mp3_file,
        )

        return mp3_file, title


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    await update.message.reply_text(
        "🎵 Send me a YouTube link and I'll send you "
        "the audio as an MP3."
    )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    if not update.message.text:
        return

    url = update.message.text.strip()

    if not is_youtube_url(url):
        await update.message.reply_text(
            "❌ Please send a valid YouTube URL."
        )
        return

    status_message = await update.message.reply_text(
        "⏳ Downloading audio..."
    )

    temp_dir = tempfile.mkdtemp(
        prefix="youtube_audio_"
    )

    try:
        mp3_file, title = await asyncio.to_thread(
            download_audio,
            url,
            temp_dir,
        )

        if not os.path.exists(mp3_file):
            raise FileNotFoundError(
                f"MP3 file was not created: {mp3_file}"
            )

        logger.info(
            "Sending MP3 to Telegram: %s",
            mp3_file,
        )

        await status_message.edit_text(
            "📤 Uploading audio..."
        )

        with open(mp3_file, "rb") as audio:
            await update.message.reply_audio(
                audio=audio,
                title=title,
                performer="YouTube",
            )

        await status_message.delete()

        logger.info(
            "Audio sent successfully."
        )

    except Exception as error:
        logger.exception(
            "Download error: %s",
            error,
        )

        try:
            await status_message.edit_text(
                "❌ Download failed.\n\n"
                f"Error: {str(error)[:1000]}"
            )
        except Exception:
            logger.exception(
                "Failed to update Telegram status message."
            )

    finally:
        try:
            for file in Path(temp_dir).glob("*"):
                if file.is_file():
                    file.unlink()

            Path(temp_dir).rmdir()

            logger.info(
                "Temporary files cleaned up."
            )

        except Exception as cleanup_error:
            logger.warning(
                "Cleanup failed: %s",
                cleanup_error,
            )


def create_application():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .updater(None)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    return application


async def main():
    application = create_application()

    webhook_path = "/telegram"

    webhook_full_url = (
        WEBHOOK_URL.rstrip("/")
        + webhook_path
    )

    await application.initialize()
    await application.start()

    await application.bot.set_webhook(
        url=webhook_full_url,
        allowed_updates=Update.ALL_TYPES,
    )

    logger.info(
        "Telegram webhook set: %s",
        webhook_full_url,
    )

    @flask_app.post(webhook_path)
    async def telegram_webhook():
        data = request.get_json(force=True)

        update = Update.de_json(
            data=data,
            bot=application.bot,
        )

        await application.update_queue.put(update)

        return Response(status=200)

    asgi_app = WsgiToAsgi(flask_app)

    config = uvicorn.Config(
        asgi_app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
    )

    server = uvicorn.Server(config)

    try:
        await server.serve()

    finally:
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())