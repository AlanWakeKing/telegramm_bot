from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    database_url: str

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
