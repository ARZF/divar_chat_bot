from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DIVAR_API_KEY: str
    DIVAR_ACCESS_TOKEN: str
    DIVAR_WEBHOOK_SECRET: str

    class Config:
        env_file = ".env"


settings = Settings()