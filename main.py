import asyncio
import logging
import sys
import time

logger=logging.getLogger(__name__)

async def _safe_wait(coro, timeout, name):
    try:
        await asyncio.wait_for(coro, timeout=timeout)
    except Exception as e:
        logger.warning("%s failed/timed out: %s", name, e)

async def _run_once():
    from bot.app import build_app
    app=build_app()
    async with app:
        if app.post_init:
            await app.post_init(app)
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        watchdog_task=None
        idle_task=None
        async def _watchdog():
            fails=0
            while True:
                await asyncio.sleep(30)
                polling_task=getattr(app.updater, "_Updater__polling_task", None)
                if not app.updater.running or polling_task is None or polling_task.done():
                    raise RuntimeError("Updater polling task stopped")
                try:
                    await asyncio.wait_for(app.bot.get_me(), timeout=10)
                    fails=0
                except Exception as e:
                    fails+=1
                    logger.warning(f"Watchdog failed ({fails}/3): {e}")
                    if fails>=3:
                        raise RuntimeError("Watchdog restart")
        try:
            watchdog_task=asyncio.create_task(_watchdog())
            idle_task=asyncio.create_task(asyncio.sleep(float("inf")))
            done,_=await asyncio.wait({watchdog_task, idle_task}, return_when=asyncio.FIRST_EXCEPTION)
            for t in done:
                exc=t.exception()
                if exc:
                    raise exc
        finally:
            if watchdog_task and not watchdog_task.done():
                watchdog_task.cancel()
            if idle_task and not idle_task.done():
                idle_task.cancel()
            await _safe_wait(app.updater.stop(), 15, "updater.stop")
            await _safe_wait(app.stop(), 15, "app.stop")
            if app.post_stop:
                await _safe_wait(app.post_stop(app), 10, "post_stop")

if __name__=="__main__":
    if len(sys.argv)>1:
        cmd=sys.argv[1]
        if cmd=="--version":
            from core.updater import VERSION
            print(f"ghostpass {VERSION}")
            sys.exit(0)
        if cmd=="update":
            from core.updater import Updater
            from config import settings
            http_proxy=settings.AUTO_UPDATE_HTTP_PROXY or ""
            https_proxy=settings.AUTO_UPDATE_HTTPS_PROXY or ""
            asyncio.run(Updater(http_proxy=http_proxy, https_proxy=https_proxy).manual_update())
            sys.exit(0)
    from config import settings
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(settings.LOG_FILE, encoding="utf-8"),
        ]
    )
    while True:
        try:
            asyncio.run(_run_once())
        except (KeyboardInterrupt, SystemExit):
            break
        except Exception as e:
            logger.critical("Bot crashed: %s, restarting in 5s", e, exc_info=True)
            time.sleep(5)
