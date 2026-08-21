from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: SecretStr
    backend_url: str = "http://localhost:8000"
    bot_admin_ids: list[int] = []

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()