from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_ROOT / "data"
DEFAULT_DB = DATA_DIR / "keel.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KEEL_", env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{DEFAULT_DB}"
    refund_threshold_cents: int = 7500
    skip_traffic: bool = False

    shopify_shop: str | None = None
    shopify_token: str | None = None
    stripe_api_key: str | None = None
    zendesk_subdomain: str | None = None
    zendesk_email: str | None = None
    zendesk_api_token: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"
    openai_model: str = "gpt-4o-mini"

    @property
    def shopify_configured(self) -> bool:
        return bool(self.shopify_shop and self.shopify_token)

    @property
    def stripe_configured(self) -> bool:
        return bool(self.stripe_api_key)

    @property
    def zendesk_configured(self) -> bool:
        return bool(self.zendesk_subdomain and self.zendesk_email and self.zendesk_api_token)

    @property
    def server_llm(self) -> bool:
        return bool(self.anthropic_api_key or self.openai_api_key)
