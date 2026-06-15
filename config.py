from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DIVAR_API_KEY: str
    DIVAR_ACCESS_TOKEN: str
    DIVAR_REFRESH_TOKEN: str
    DIVAR_WEBHOOK_SECRET: str
    DIVAR_IDENTIFICATION_KEY: str
    DIVAR_APP_SLUG: str
    DIVAR_CLIENT_SECRET: str
    DIVAR_REDIRECT_URI: str
    admin_token: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
