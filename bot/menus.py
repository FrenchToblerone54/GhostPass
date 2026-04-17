from telegram import BotCommand
from config import settings
from bot.strings import t

async def register_commands(bot):
    en_cmds = [
        BotCommand("start", "Start the bot"),
        BotCommand("plans", "Browse VPN plans"),
        BotCommand("mystatus", "Check my subscription"),
        BotCommand("support", "Get support"),
    ]
    fa_cmds = [
        BotCommand("start", "شروع ربات"),
        BotCommand("plans", "مشاهده پلان‌ها"),
        BotCommand("mystatus", "وضعیت اشتراک من"),
        BotCommand("support", "دریافت پشتیبانی"),
    ]
    await bot.set_my_commands(en_cmds, language_code="en")
    await bot.set_my_commands(fa_cmds, language_code="fa")
    await bot.set_my_commands(fa_cmds if settings.LANGUAGE.lower()=="fa" else en_cmds)
