# YouTube Audio Telegram Bot

A Telegram bot that downloads audio from YouTube URLs and sends it as an MP3 file.

## Features

- YouTube URL → MP3
- Audio only
- No video sent to Telegram
- Uses yt-dlp
- Uses FFmpeg
- Temporary files are deleted after sending
- Deployable on Render
- No Docker required

## Technologies

- Python
- python-telegram-bot
- yt-dlp
- FFmpeg
- Flask
- Uvicorn
- Render

## Environment Variables

### BOT_TOKEN

Telegram bot token from BotFather.

### WEBHOOK_URL

Your Render service URL.

Example:

https://your-bot-name.onrender.com

## Run

```bash
pip install -r requirements.txt
python app.py