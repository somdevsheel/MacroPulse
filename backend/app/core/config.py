"""Application settings, loaded from environment variables / the repo-root .env file.

Credentials live only here (server side). Nothing in this module is ever sent to the frontend;
use `Settings.provider_key_status()` to expose *whether* a key is configured, never its value.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str | None = None
    data_dir: Path = REPO_ROOT / "data"

    fred_api_key: SecretStr | None = None
    trading_economics_api_key: SecretStr | None = None
    bls_api_key: SecretStr | None = None
    bea_api_key: SecretStr | None = None
    oanda_api_token: SecretStr | None = None
    oanda_environment: str = "practice"
    twelve_data_api_key: SecretStr | None = None

    log_level: str = "INFO"
    log_json: bool = False

    def resolved_data_dir(self) -> Path:
        p = self.data_dir
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    def provider_key_status(self) -> dict[str, bool]:
        """Which credentials are present. Safe to expose: booleans only."""
        keys = {
            "fred": self.fred_api_key,
            "trading_economics": self.trading_economics_api_key,
            "bls": self.bls_api_key,
            "bea": self.bea_api_key,
            "oanda": self.oanda_api_token,
            "twelve_data": self.twelve_data_api_key,
        }
        return {k: bool(v and v.get_secret_value().strip()) for k, v in keys.items()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
