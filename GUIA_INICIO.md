# Guía de inicio — Finanzas local

Finanzas corre 100% en tu máquina (GLO-07): Postgres nativo, un servicio
`systemd --user` con FastAPI que también sirve el frontend compilado, y un
lanzador de escritorio. Sin login: la app actúa siempre como tu perfil
(`LOCAL_USER_ID`). Respaldos diarios automáticos (GLO-08).

```
 Lanzador "Finanzas" ──▶ ~/.local/bin/finanzas-open ──▶ Brave --app
                                                          │
                                         http://127.0.0.1:8765
                                                          ▼
   systemd --user: finanzas.service (uvicorn, jobs APScheduler)
          │  SPA (frontend/dist) + /api/v1
          ▼
   Postgres local (socket /run/postgresql, sin red)  ──▶ respaldo diario
                                                          ~/Documents/finanzas-backups
```

## Instalación (una vez)

```bash
scripts/local/setup-postgres.sh      # SIN sudo delante (lo pide solo): instala Postgres y crea la base
scripts/local/install.sh             # build + migraciones + servicio + lanzador
```

## Día a día

| Qué | Comando |
|---|---|
| Abrir la app | lanzador **Finanzas** (o `finanzas-open`) |
| Actualizar tras cambiar código | `scripts/local/install.sh` |
| Logs | `journalctl --user -u finanzas -f` |
| Reiniciar | `systemctl --user restart finanzas` |
| Respaldo manual | `scripts/local/backup.sh` |
| Restaurar un respaldo | `pg_restore --clean --if-exists -h /run/postgresql -d finanzas <archivo.dump>` |

La configuración del servicio vive en `~/.config/finanzas/finanzas.env` y tiene
prioridad sobre `backend/.env` (de ahí solo se toman las API keys de
CoinGecko/Banxico).

## Desarrollo

Sin cambios: `uv run uvicorn app.main:app --reload` (:8000) + `npm run dev`
(:5173). En `backend/.env` usa la base local y tu id:

```
DATABASE_URL=postgresql+asyncpg://<tu-usuario>@/finanzas?host=/run/postgresql
AUTH_MODE=local
LOCAL_USER_ID=<el de ~/.config/finanzas/finanzas.env>
```

El servicio instalado usa el puerto 8765, así que ambos conviven. Para no
tocar tus datos reales, crea otra base (`createdb finanzas_dev`) y apunta ahí.
