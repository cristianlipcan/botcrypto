import os
import asyncio
from telegram import Bot
import logging

logging.basicConfig(level=logging.INFO)

async def test_telegram():
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logging.error("TELEGRAM_TOKEN sau TELEGRAM_CHAT_ID nu sunt setate!")
        return
    bot = Bot(token=token)
    try:
        await bot.send_message(chat_id=chat_id, text="✅ Test bot Railway funcționează!")
        logging.info("Mesaj trimis cu succes.")
    except Exception as e:
        logging.exception("Eroare la trimiterea mesajului: %s", e)

if __name__ == "__main__":
    asyncio.run(test_telegram())
