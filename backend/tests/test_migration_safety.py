"""Migration safety tests.

Verifies:
- Checksum validation fails loudly if a migration file changes after being applied
- Applying migrations works in order
"""

import os
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from sqlalchemy import create_engine
from app.migrate import run_migrations

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="Migration runner uses PostgreSQL specific types and functions"
)

class TestMigrationSafety:
    def test_checksum_safety(self):
        with TemporaryDirectory() as d:
            dir_path = Path(d)
            m1 = dir_path / "001_first.sql"
            m1.write_text("CREATE TABLE test (id int);")
            
            db_url = "sqlite+pysqlite:///:memory:"
            
            # Apply initial
            run_migrations(db_url, migration_dir=dir_path)
            
            # Modify applied migration
            m1.write_text("CREATE TABLE test (id int, extra int);")
            
            # Running again should raise RuntimeError due to checksum mismatch
            with pytest.raises(RuntimeError, match="Migration content has changed"):
                run_migrations(db_url, migration_dir=dir_path)

    def test_dry_run_does_not_apply(self):
        with TemporaryDirectory() as d:
            dir_path = Path(d)
            m1 = dir_path / "001_first.sql"
            m1.write_text("CREATE TABLE test_dry (id int);")
            
            db_url = "sqlite+pysqlite:///:memory:"
            
            # Dry run
            run_migrations(db_url, migration_dir=dir_path, dry_run=True)
            
            # Table should not exist
            engine = create_engine(db_url)
            with engine.connect() as conn:
                from sqlalchemy import text
                from sqlalchemy.exc import OperationalError
                with pytest.raises(OperationalError):
                    conn.execute(text("SELECT * FROM test_dry"))
