from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional

class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_ID: int
    BOT_PROXY: Optional[str] = None
    GHOSTGATE_URL: str = ""
    BTCPAY_URL: str = ""
    BTCPAY_STORE_ID: str = ""
    BTCPAY_API_KEY: str = ""
    GHOSTPAYMENTS_URL: str = ""
    GHOSTPAYMENTS_API_KEY: str = ""
    GHOSTPAYMENTS_CHAIN: str = "BSC"
    GHOSTPAYMENTS_TOKEN: str = "USDT"
    USDT_TRC20_ADDRESS: str = ""
    USDT_BSC_ADDRESS: str = ""
    USDT_POLYGON_ADDRESS: str = ""
    SYNC_INTERVAL: int = 60
    LANGUAGE: str = "en"
    AUTO_UPDATE: bool = True
    CHECK_ON_STARTUP: bool = True
    UPDATE_CHECK_INTERVAL: int = 300
    AUTO_UPDATE_HTTP_PROXY: Optional[str] = None
    AUTO_UPDATE_HTTPS_PROXY: Optional[str] = None
    DB_PATH: str = "/opt/ghostpass/ghostpass.db"
    LOG_FILE: str = "/var/log/ghostpass.log"

    @field_validator("GHOSTGATE_URL")
    @classmethod
    def strip_trailing_slash(cls, v):
        return v.rstrip("/")

    class Config:
        env_file = "/opt/ghostpass/.env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
