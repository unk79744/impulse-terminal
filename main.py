import asyncio
import logging
import os
import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from config import BOT_TOKEN
from database import init_db
from bot_handlers import router
from screener import run_screener
from payments import close_session as close_crypto_session
from middlewares import SubscriptionMiddleware
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

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

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found!")
        return

    await init_db()
    
    session = CustomAiohttpSession()
    bot = Bot(token=BOT_TOKEN, session=session)
    dp = Dispatcher()
    
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())
    
    dp.include_router(router)
    
    screener_task = asyncio.create_task(run_screener(bot))
    
    try:
        logger.info(">>> IMPULSE TERMINAL STARTED <<<")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Main Loop Error: {e}")
    finally:
        logger.info("Shutting down services...")
        screener_task.cancel()
        try:
            await screener_task
        except asyncio.CancelledError:
            pass
        await close_crypto_session()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass