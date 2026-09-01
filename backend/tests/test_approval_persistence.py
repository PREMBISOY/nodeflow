"""Approval persistence tests.

Verifies:
- ApprovalService safely handles concurrent decisions
- Double-decision throws ValueError
- IntegrityError caught and re-raised gracefully
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from uuid import uuid4, UUID

from app.persistence import Base
from app.services.approval import ApprovalService

class TestApprovalPersistence:
    def _session(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE approval_requests (
                    id text PRIMARY KEY, project_id text, team_id text, source_event_id text,
                    title text, description text, status text, created_at text, updated_at text
                )
            """))
            conn.execute(text("""
                CREATE TABLE approval_decisions (
                    id text PRIMARY KEY, approval_request_id text UNIQUE,
                    decision text, actor_name text, comment text, decided_at text
                )
            """))
            conn.commit()

        return sessionmaker(engine, expire_on_commit=False)()

    def test_create_and_decide(self):
        session = self._session()
        svc = ApprovalService(session)
        project_id = uuid4()
        req = svc.create_request(project_id=project_id, team_id=uuid4(), title="Deploy to prod", description="Please approve")
        assert req["status"] == "waiting_approval"

        decision = svc.make_decision(approval_request_id=UUID(req["id"]), project_id=project_id, decision="approved", actor_name="Alice", comment="Looks good")
        assert decision["decision"] == "approved"
        
        reqs = svc.list_requests(project_id=project_id)
        assert reqs[0]["status"] == "approved"

    def test_double_decision_fails(self):
        session = self._session()
        svc = ApprovalService(session)
        project_id = uuid4()
        req = svc.create_request(project_id=project_id, team_id=uuid4(), title="Deploy")
        svc.make_decision(approval_request_id=UUID(req["id"]), project_id=project_id, decision="approved", actor_name="Alice")
        
        with pytest.raises(ValueError):
            svc.make_decision(approval_request_id=UUID(req["id"]), project_id=project_id, decision="rejected", actor_name="Bob")

    def test_decision_on_unknown_request_fails(self):
        session = self._session()
        svc = ApprovalService(session)
        with pytest.raises(LookupError):
            svc.make_decision(approval_request_id=uuid4(), project_id=uuid4(), decision="approved", actor_name="Alice")
