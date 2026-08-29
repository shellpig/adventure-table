from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Adventure Table API"
    database_url: str = (
        "postgresql+psycopg://adventure:adventure@localhost:5432/adventure_table"
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
