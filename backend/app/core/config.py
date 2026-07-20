from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Default de desarrollo local (credenciales por defecto de la imagen de Postgres).
# Fuera de env=dev es obligatorio definir DATABASE_URL: ver _reject_dev_defaults.
DEV_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/finanzas"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = DEV_DATABASE_URL
    cors_origins: list[str] = ["http://localhost:5173"]
    # Jobs (REC-02, FX-02): enable once the DB is configured.
    scheduler_enabled: bool = False

    # Supabase Auth (verificación de JWT, ver app/core/security.py).
    # Proyectos nuevos (JWT Signing Keys asimétricas): solo SUPABASE_URL.
    # Proyectos legacy (HS256): además SUPABASE_JWT_SECRET.
    supabase_url: str = ""
    supabase_jwt_secret: str = ""

    # Precios (INV-03) — la key jamás sale del backend
    coingecko_api_key: str = ""
    coinmarketcap_api_key: str = ""

    # FX (FX-02)
    banxico_token: str = ""

    @model_validator(mode="after")
    def _reject_dev_defaults(self) -> "Settings":
        """CWE-1188: fuera de dev, una config faltante debe fallar fuerte.

        Sin esto, un despliegue sin DATABASE_URL arrancaría silenciosamente
        apuntando a un Postgres local con credenciales por defecto.
        """
        if self.env != "dev" and self.database_url == DEV_DATABASE_URL:
            raise ValueError(f"DATABASE_URL debe definirse explícitamente cuando ENV={self.env!r}")
        return self


settings = Settings()
