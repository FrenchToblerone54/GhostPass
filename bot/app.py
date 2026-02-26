import logging
from telegram.ext import ApplicationBuilder, Application
from config import settings
from bot.menus import register_commands
from core.db import init_db
import bot.handlers.admin as admin_h
import bot.handlers.consumer as consumer_h
import bot.handlers.payment_card as card_h
import bot.handlers.payment_crypto as crypto_h
import bot.handlers.payment_request as request_h

logger = logging.getLogger(__name__)

async def _post_init(app: Application):
    await init_db()
    await register_commands(app.bot)
    logger.info("GhostPass started")

async def build_app() -> Application:
    builder = ApplicationBuilder().token(settings.BOT_TOKEN).post_init(_post_init)
    if settings.BOT_PROXY:
        builder = builder.proxy(settings.BOT_PROXY).get_updates_proxy(settings.BOT_PROXY)
    app = builder.build()
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
