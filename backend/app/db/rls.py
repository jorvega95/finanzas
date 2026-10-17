"""RLS guard for migrations (GLO-05, GLO-07).

The RLS policies use Supabase's `auth.uid()`. On a plain local Postgres
(GLO-07) that function does not exist, so policies are skipped and FastAPI's
space filtering is the only isolation layer.
"""

from sqlalchemy import text
from sqlalchemy.engine import Connection


def supports_rls(bind: Connection) -> bool:
    """True only on Postgres with Supabase's `auth.uid()` available."""
    if bind.dialect.name != "postgresql":
        return False
    found = bind.execute(
        text(
            "SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'auth' AND p.proname = 'uid'"
        )
    ).first()
    return found is not None
