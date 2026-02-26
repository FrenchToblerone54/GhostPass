import asyncio
import logging
from telegram.ext import ApplicationBuilder, Application
from config import settings
from bot.menus import register_commands
from core.db import init_db
from core.sync import run_sync_worker
from core.updater import Updater
import bot.handlers.admin as admin_h
import bot.handlers.consumer as consumer_h
import bot.handlers.payment_card as card_h
import bot.handlers.payment_crypto as crypto_h
import bot.handlers.payment_request as request_h

logger = logging.getLogger(__name__)

async def _post_init(app: Application):
    await init_db()
    await register_commands(app.bot)
    asyncio.create_task(run_sync_worker(app.bot))
    asyncio.create_task(crypto_h.run_webhook_server(app.bot))
    if settings.AUTO_UPDATE:
        proxy=settings.BOT_PROXY or ""
        updater=Updater(check_interval=settings.UPDATE_CHECK_INTERVAL, check_on_startup=settings.CHECK_ON_STARTUP, http_proxy=proxy, https_proxy=proxy)
        shutdown_event=asyncio.Event()
        app.bot_data["shutdown_event"]=shutdown_event
        asyncio.create_task(updater.update_loop(shutdown_event))
    logger.info("GhostPass started")

async def _post_stop(app: Application):
    shutdown_event=app.bot_data.get("shutdown_event")
    if shutdown_event:
        shutdown_event.set()

def build_app() -> Application:
    builder=ApplicationBuilder().token(settings.BOT_TOKEN).post_init(_post_init).post_stop(_post_stop).concurrent_updates(True)
    if settings.BOT_PROXY:
        builder=builder.proxy(settings.BOT_PROXY).get_updates_proxy(settings.BOT_PROXY)
    app=builder.build()
    _register_handlers(app)
    return app

def _register_handlers(app: Application):
    for h in admin_h.get_handlers():
        app.add_handler(h, group=0)
    for h in card_h.get_handlers():
        app.add_handler(h, group=1)
    for h in crypto_h.get_handlers():
        app.add_handler(h, group=1)
    for h in request_h.get_handlers():
        app.add_handler(h, group=1)
    for h in consumer_h.get_handlers():
        app.add_handler(h, group=2)
