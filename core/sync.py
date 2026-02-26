import asyncio
import logging
from datetime import datetime, timezone
from config import settings
import core.db as db
import core.ghostgate as gg

logger = logging.getLogger(__name__)

async def run_sync_worker(bot=None):
    while True:
        try:
            await asyncio.sleep(settings.SYNC_INTERVAL)
            await _sync_tick(bot)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error("Sync worker error: %s", e)

async def _sync_tick(bot):
    try:
        subs = await gg.list_subscriptions(per_page=0)
        live_ids = {s["id"] for s in subs}
        paid_orders = await db.get_paid_orders_with_sub()
        for order in paid_orders:
            if order["ghostgate_sub_id"] not in live_ids:
                await db.update_order(order["id"], status="cancelled")
                if bot:
                    try:
                        await bot.send_message(
                            order["telegram_id"],
                            "\u26a0\ufe0f Your subscription has been removed from the server. Please contact support."
                        )
                    except Exception:
                        pass
    except Exception as e:
        logger.error("Sync tick error: %s", e)
