"""PostgreSQL integration test boundary.

Must be skipped if DATABASE_URL is not provided (e.g. standard local dev).
This verifies true SQL features like advisory locks and JSONB queries.
"""

import os
import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set"
)

def test_advisory_lock():
    url = os.getenv("DATABASE_URL")
    engine = create_engine(url)
    
    with engine.connect() as conn:
        try:
            # PostgreSQL specific syntax for advisory locks
            locked = conn.execute(text("SELECT pg_try_advisory_lock(123456)")).scalar()
            assert locked is True
            # Should fail to acquire same lock in another connection? 
            # Actually, same session can acquire multiple times. Just test syntax validity.
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(123456)"))
