from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings

# pool_pre_ping: descarta conexiones muertas antes de usarlas (el pooler de
# Supabase cierra las inactivas → evita "connection is closed").
# pool_recycle: recicla conexiones antes de que el pooler las cierre.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=300,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
