import asyncio
import aiosqlite
import aiohttp
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from config import BOT_TOKEN, DB_NAME

class CustomAiohttpSession(AiohttpSession):
    async def create_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            resolver = aiohttp.ThreadedResolver()
            connector = aiohttp.TCPConnector(resolver=resolver)
            self._session = aiohttp.ClientSession(
                connector=connector,
                json_serialize=self.json_dumps,
            )
        return self._session

async def send_demos():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id FROM users LIMIT 1")
        row = await cursor.fetchone()
        if not row:
            print("❌ Сначала напиши /start боту в Telegram!")
            return
        user_id = row[0]

    session = CustomAiohttpSession()
    bot = Bot(token=BOT_TOKEN, session=session)

    signals = "<b>#ИДИ НАХУЙ!</b>" 

    print(f"🚀 Отправка 3 сигналов пользователю ID: {user_id}...")
    for i in range(100):
        await bot.send_message(user_id, signals, parse_mode="HTML")
        await asyncio.sleep(1)
    
    print("✅ Все 3 сигнала успешно доставлены в Telegram! Заходи и скринь.")
    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(send_demos())