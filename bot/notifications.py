import asyncio
import logging
import core.db as db
from config import settings

logger = logging.getLogger(__name__)

async def admin_event(bot, setting_key, text):
    if await db.get_setting(setting_key, "0") != "1":
        return
    for admin_id in await db.get_all_admin_ids(settings.ADMIN_ID):
        try:
            await bot.send_message(admin_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.error("admin_event notify %s: %s", admin_id, e)
