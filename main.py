import asyncio
import logging
import sys
from bot.app import build_app
from core.sync import run_sync_worker
from core.updater import Updater
from bot.handlers.payment_crypto import run_webhook_server
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(settings.LOG_FILE, encoding="utf-8"),
    ]
)

async def main():
    shutdown_event=asyncio.Event()
    app=await build_app()
    asyncio.create_task(run_sync_worker(app.bot))
    asyncio.create_task(run_webhook_server(app.bot))
    if settings.AUTO_UPDATE:
        proxy=settings.BOT_PROXY or ""
        updater=Updater(check_interval=settings.UPDATE_CHECK_INTERVAL, check_on_startup=True, http_proxy=proxy, https_proxy=proxy)
        asyncio.create_task(updater.update_loop(shutdown_event))
    await app.run_polling(drop_pending_updates=True)
    shutdown_event.set()

if __name__=="__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.critical("Fatal crash: %s", e, exc_info=True)
        sys.exit(1)
