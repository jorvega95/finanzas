from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/finanzas"
    cors_origins: list[str] = ["http://localhost:5173"]
    # Jobs (REC-02, FX-02): enable once the DB is configured.
    scheduler_enabled: bool = False

    # Supabase Auth (verificación de JWT, ver app/core/security.py)
    supabase_url: str = ""
    supabase_jwt_secret: str = ""

    # Precios (INV-03) — la key jamás sale del backend
    coingecko_api_key: str = ""
    coinmarketcap_api_key: str = ""

    # FX (FX-02)
    banxico_token: str = ""


settings = Settings()
