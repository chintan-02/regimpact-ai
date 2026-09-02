import json
from unittest import TestCase
from uuid import uuid4

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from regimpact.agent_evaluation import evaluate
from regimpact.agent_workflow import create_workflow, decide_workflow
from regimpact.control_mapping import add_control, suggest_mappings
from regimpact.database import Base
from regimpact.db_models import (
    AgentWorkflowDecisionRecord,
    AuditEventRecord,
    ObligationControlMappingRecord,
    ObligationRecord,
    OrganizationRecord,
    RegulationRecord,
)
from regimpact.domain import Section
from regimpact.obligation_service import extract_and_store_obligations
from regimpact.repository import RegulationNotFoundError, SqlAlchemyVersionRepository
from regimpact.versioning import VersioningService


class AgentWorkflowTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.organization_id = uuid4()
        regulation_id = uuid4()
        self.session.add(OrganizationRecord(id=self.organization_id, name="Northstar"))
        self.session.add(
            RegulationRecord(
                id=regulation_id,
                organization_id=self.organization_id,
                source_key="AER-D060",
                title="Directive 060",
                jurisdiction="Alberta",
            )
        )
        self.session.flush()
        version = VersioningService(
            SqlAlchemyVersionRepository(self.session, self.organization_id, "seed")
        ).ingest(
            regulation_id=regulation_id,
            source_uri="https://www.aer.ca/directive-060",
            raw_content="Operators must report incidents.",
            sections=(Section("4.2", "Notification", "Operators must report incidents.", 43),),
        )
        extract_and_store_obligations(
            self.session,
            organization_id=self.organization_id,
            version_id=version.version.id,
            actor_id="seed",
        )
        add_control(
            self.session,
            organization_id=self.organization_id,
            control_key="REG-IR-01",
            title="Incident reporting",
            description="Report incidents",
            owner="Compliance",
            evidence_requirement="Receipt",
        )
        obligation = self.session.scalar(select(ObligationRecord))
        assert obligation
        self.obligation_id = obligation.id
        suggest_mappings(
            self.session,
            organization_id=self.organization_id,
            obligation_id=obligation.id,
            actor_id="seed",
        )
        self.session.flush()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_proposal_is_grounded_gated_and_idempotent(self):
        run, created = create_workflow(
            self.session,
            organization_id=self.organization_id,
            obligation_id=self.obligation_id,
            goal="Assess the regulatory control impact.",
            actor_id="user:analyst",
            idempotency_key="agent-run-0001",
        )
        duplicate, duplicate_created = create_workflow(
            self.session,
            organization_id=self.organization_id,
            obligation_id=self.obligation_id,
            goal="Assess the regulatory control impact.",
            actor_id="user:analyst",
            idempotency_key="agent-run-0001",
        )
        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(run.id, duplicate.id)
        self.assertEqual(run.status, "awaiting_approval")
        evidence = json.loads(run.evidence_json)
        policies = json.loads(run.policy_results_json)
        self.assertEqual(evidence["page"], 43)
        self.assertTrue(policies["human_approval_required"])
        self.assertTrue(policies["automatic_execution_disabled"])

    def test_high_risk_requires_different_approver_and_is_audited(self):
        run, _ = create_workflow(
            self.session,
            organization_id=self.organization_id,
            obligation_id=self.obligation_id,
            goal="Assess the regulatory control impact.",
            actor_id="user:analyst",
            idempotency_key="agent-run-0002",
        )
        with self.assertRaises(ValueError):
            decide_workflow(
                self.session,
                organization_id=self.organization_id,
                run_id=run.id,
                decision="approved",
                rationale="I approve my own high risk proposal.",
                actor_id="user:analyst",
                idempotency_key="agent-decision-self",
                expected_revision=0,
            )
        decision = decide_workflow(
            self.session,
            organization_id=self.organization_id,
            run_id=run.id,
            decision="approved",
            rationale="Evidence and control ownership were independently verified.",
            actor_id="user:admin",
            idempotency_key="agent-decision-admin",
            expected_revision=0,
        )
        self.assertEqual(decision.revision, 1)
        self.assertEqual(run.status, "approved")
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(AgentWorkflowDecisionRecord)), 1
        )
        self.assertGreaterEqual(
            self.session.scalar(select(func.count()).select_from(AuditEventRecord)) or 0, 2
        )

    def test_evaluation_detects_unsafe_execution(self):
        metrics = evaluate(
            [
                {
                    "citation_complete": True,
                    "tenant_scope": True,
                    "human_approval_required": True,
                    "automatic_execution_allowed": False,
                    "proposal_supported": True,
                    "policy_block_expected": False,
                    "policy_blocked": False,
                },
                {
                    "citation_complete": False,
                    "tenant_scope": True,
                    "human_approval_required": True,
                    "automatic_execution_allowed": False,
                    "proposal_supported": False,
                    "policy_block_expected": True,
                    "policy_blocked": True,
                },
            ]
        )
        self.assertEqual(metrics.unsafe_execution_rate, 0)
        self.assertEqual(metrics.policy_block_accuracy, 1)
        self.assertEqual(metrics.groundedness_rate, 0.5)

    def test_tenant_boundary_hides_foreign_obligation(self):
        with self.assertRaises(RegulationNotFoundError) as raised:
            create_workflow(
                self.session,
                organization_id=uuid4(),
                obligation_id=self.obligation_id,
                goal="Assess the regulatory control impact.",
                actor_id="user:foreign-analyst",
                idempotency_key="agent-run-foreign",
            )
        self.assertEqual(str(raised.exception), "obligation not found")

    def test_policy_blocked_workflow_cannot_be_approved(self):
        self.session.execute(delete(ObligationControlMappingRecord))
        run, _ = create_workflow(
            self.session,
            organization_id=self.organization_id,
            obligation_id=self.obligation_id,
            goal="Assess the regulatory control impact.",
            actor_id="user:analyst",
            idempotency_key="agent-run-blocked",
        )
        self.assertEqual(run.status, "blocked")
        with self.assertRaisesRegex(ValueError, "policy-blocked"):
            decide_workflow(
                self.session,
                organization_id=self.organization_id,
                run_id=run.id,
                decision="approved",
                rationale="Attempt to approve a blocked proposal.",
                actor_id="user:admin",
                idempotency_key="agent-decision-blocked",
                expected_revision=0,
            )
