import asyncio
import logging
import sys
import time
from bot.app import build_app
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(settings.LOG_FILE, encoding="utf-8"),
    ]
)

logger = logging.getLogger(__name__)

async def _run_once():
    app = build_app()
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        async def _watchdog():
            fails = 0
            while True:
                await asyncio.sleep(30)
                try:
                    await asyncio.wait_for(app.bot.get_me(), timeout=10)
                    fails = 0
                except Exception as e:
                    fails += 1
                    logger.warning(f"Watchdog failed ({fails}/3): {e}")
                    if fails >= 3:
                        raise RuntimeError("Watchdog restart")
        try:
            await asyncio.gather(asyncio.sleep(float("inf")), _watchdog())
        finally:
            await app.updater.stop()
            await app.stop()

if __name__=="__main__":
    while True:
        try:
            asyncio.run(_run_once())
        except (KeyboardInterrupt, SystemExit):
            break
        except Exception as e:
            logger.critical("Bot crashed: %s, restarting in 5s", e, exc_info=True)
            time.sleep(5)
