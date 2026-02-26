import logging
import sys
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

if __name__=="__main__":
    try:
        build_app().run_polling(drop_pending_updates=True)
    except Exception as e:
        logging.critical("Fatal crash: %s", e, exc_info=True)
        sys.exit(1)
