from telegram import BotCommand

CONSUMER_COMMANDS = [
    BotCommand("start", "Start the bot"),
    BotCommand("plans", "Browse VPN plans"),
    BotCommand("mystatus", "Check my subscription"),
    BotCommand("support", "Get support"),
]

async def register_commands(bot):
    await bot.set_my_commands(CONSUMER_COMMANDS)
