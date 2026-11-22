from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://spartan:spartanpass@localhost:5432/spartan_lab"
    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "INFO"
    rate_limit_per_minute: int = 120


settings = Settings()
