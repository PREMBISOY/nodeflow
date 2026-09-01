"""Tests for the SQLAlchemy persistence adapter.

These tests use an in-memory SQLite database and manage the session lifecycle
directly (no request-scoped middleware). They call session.commit() explicitly
after setup operations since the unit-of-work middleware is not active here.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.fixtures.demo_data import DEMO_IDS, seed_demo
from app.models import Event
from app.persistence import Base, SqlAlchemyProjectRepository


def build_repository() -> SqlAlchemyProjectRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(engine, expire_on_commit=False)()
    repository = SqlAlchemyProjectRepository(session)
    seed_demo(repository)
    # Commit seed data: in this direct-session context (no middleware), we own
    # the transaction lifecycle.
    session.commit()
    return repository


def test_adapter_satisfies_project_brain_read_contract():
    repository = build_repository()
    assert repository.get_project(DEMO_IDS["project"]).name == "NodeFlow"
    assert len(repository.list_components(DEMO_IDS["project"])) == 4
    assert len(repository.list_relationships(DEMO_IDS["project"])) == 2


def test_adapter_persists_event_contract():
    repository = build_repository()
    event = repository.add_event(Event(project_id=DEMO_IDS["project"], event_type="test_completed", summary="Adapter test passed"))
    # Flush is enough to make it visible within the same session; commit for durability
    repository.session.commit()
    assert repository.list_events(DEMO_IDS["project"])[0].id == event.id
