from telegram import BotCommand
from config import settings

CONSUMER_COMMANDS = [
    BotCommand("start", "Start the bot"),
    BotCommand("plans", "Browse VPN plans"),
    BotCommand("mystatus", "Check my subscription"),
    BotCommand("support", "Get support"),
]

CONSUMER_COMMANDS_FA = [
    BotCommand("start", "شروع ربات"),
    BotCommand("plans", "مشاهده پلان‌ها"),
    BotCommand("mystatus", "وضعیت اشتراک من"),
    BotCommand("support", "دریافت پشتیبانی"),
]

async def register_commands(bot):
    await bot.set_my_commands(CONSUMER_COMMANDS, language_code="en")
    await bot.set_my_commands(CONSUMER_COMMANDS_FA, language_code="fa")
    await bot.set_my_commands(CONSUMER_COMMANDS_FA if settings.LANGUAGE.lower()=="fa" else CONSUMER_COMMANDS)
