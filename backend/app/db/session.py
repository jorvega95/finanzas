from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings

# pool_pre_ping: descarta conexiones muertas (p. ej. tras reiniciar Postgres
# o suspender la laptop) antes de usarlas.
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
