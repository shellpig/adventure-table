from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


_DEFAULT_PACKS = (
    "srd5.1",
    "phb2014",
    "scag",
    "gos",
    "vgm",
    "vrgr",
    "tce",
    "xge",
    "mtf",
)


class Settings(BaseSettings):
    app_name: str = "Adventure Table API"
    database_url: str = (
        "postgresql+psycopg://adventure:adventure@localhost:5432/adventure_table"
    )
    content_root: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ADVENTURE_TABLE_CONTENT_ROOT"),
    )
    database_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ADVENTURE_TABLE_DATABASE_PATH"),
    )
    spa_root: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ADVENTURE_TABLE_SPA_ROOT"),
    )
    enabled_content_packs: Annotated[tuple[str, ...], NoDecode] = Field(
        default=_DEFAULT_PACKS,
        validation_alias=AliasChoices("ADVENTURE_TABLE_ENABLED_CONTENT_PACKS"),
    )

    # Do not add env_prefix: the existing Docker contract reads DATABASE_URL.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("enabled_content_packs", mode="before")
    @classmethod
    def _parse_pack_list(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            parts = tuple(part.strip() for part in value.split(",") if part.strip())
            return parts or _DEFAULT_PACKS
        if isinstance(value, Iterable):
            return tuple(str(part) for part in value)
        return _DEFAULT_PACKS


settings = Settings()
