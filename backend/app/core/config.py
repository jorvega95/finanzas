import uuid
from typing import Literal

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

    # Auth (GLO-07). "local": mono-usuario sin token, todo actúa como
    # LOCAL_USER_ID (solo con el servidor en 127.0.0.1). "jwt": Bearer HS256
    # firmado con JWT_SECRET (tests y un futuro cliente remoto/móvil).
    auth_mode: Literal["local", "jwt"] = "local"
    local_user_id: uuid.UUID | None = None
    local_user_email: str | None = None
    jwt_secret: str = ""
    # GLO-07: hostnames extra (separados por coma) aceptados además de loopback,
    # p. ej. el nombre MagicDNS de Tailscale detrás de `tailscale serve`.
    trusted_hosts: str = ""

    # Frontend compilado (frontend/dist) servido por FastAPI (GLO-07). Vacío =
    # no se sirve (desarrollo con Vite en :5173).
    frontend_dist: str = ""

    # Precios (INV-03) — la key jamás sale del backend
    coingecko_api_key: str = ""
    coinmarketcap_api_key: str = ""

    # FX (FX-02)
    banxico_token: str = ""

    # REM-08: desktop notifications (notify-send) in local mode, never before
    # this local hour.
    desktop_notifications: bool = False
    desktop_notify_hour: int = 9

    @property
    def trusted_host_list(self) -> list[str]:
        return [h.strip().lower() for h in self.trusted_hosts.split(",") if h.strip()]

    @model_validator(mode="after")
    def _reject_dev_defaults(self) -> "Settings":
        """CWE-1188: fuera de dev, una config faltante debe fallar fuerte.

        Sin esto, un despliegue sin DATABASE_URL arrancaría silenciosamente
        apuntando a un Postgres local con credenciales por defecto.
        """
        if self.env != "dev" and self.database_url == DEV_DATABASE_URL:
            raise ValueError(f"DATABASE_URL debe definirse explícitamente cuando ENV={self.env!r}")
        if self.auth_mode == "jwt" and not self.jwt_secret:
            raise ValueError("AUTH_MODE=jwt requiere JWT_SECRET")
        return self


settings = Settings()
