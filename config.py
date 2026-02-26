from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional

class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_ID: int
    BOT_PROXY: Optional[str] = None
    GHOSTGATE_URL: str = ""
    SYNC_INTERVAL: int = 60
    LANGUAGE: str = "en"
    AUTO_UPDATE: bool = True
    UPDATE_CHECK_INTERVAL: int = 300
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
