"""Versioned HTTP request and response contracts."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)


class DemoLoginRequest(BaseModel):
    role: str = Field(pattern=r"^(admin|analyst|viewer)$")


class AuthenticatedUserResponse(BaseModel):
    id: UUID
    organization_id: UUID
    organization_name: str
    email: str
    display_name: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthenticatedUserResponse


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=2, max_length=200)
    role: str = Field(pattern=r"^(admin|analyst|viewer)$")
    password: str = Field(min_length=12, max_length=200)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    email: str
    display_name: str
    role: str
    active: bool
    created_at: datetime
    last_login_at: datetime | None


class OrganizationCreate(BaseModel):
    id: UUID
    name: str = Field(min_length=2, max_length=200)


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    created_at: datetime


class RegulationCreate(BaseModel):
    source_key: str = Field(min_length=2, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    title: str = Field(min_length=3, max_length=500)
    jurisdiction: str = Field(min_length=2, max_length=120)


class RegulationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    source_key: str
    title: str
    jurisdiction: str
    created_at: datetime


class SectionInput(BaseModel):
    key: str = Field(min_length=1, max_length=160)
    heading: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)


class VersionCreate(BaseModel):
    source_uri: HttpUrl
    raw_content: str = Field(min_length=1)
    effective_date: date | None = None
    sections: list[SectionInput] = Field(min_length=1, max_length=10_000)


class ChangeResponse(BaseModel):
    section_key: str
    heading: str
    change_type: str
    previous_page: int | None
    current_page: int | None


class VersionResponse(BaseModel):
    id: UUID
    regulation_id: UUID
    ordinal: int
    content_hash: str
    created: bool
    change_count: int
    changes: list[ChangeResponse]


class IngestionJobState(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    regulation_id: UUID
    status: str
    original_filename: str
    media_type: str
    size_bytes: int
    content_hash: str
    resulting_version_id: UUID | None
    error_code: str | None
    error_message: str | None
    attempt_count: int
    max_attempts: int
    failure_class: str | None
    next_retry_at: datetime | None
    lease_expires_at: datetime | None
    last_heartbeat_at: datetime | None
    replay_count: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class IngestionJobResponse(IngestionJobState):
    created: bool = True


class RegulatorySourceCreate(BaseModel):
    regulation_id: UUID
    name: str = Field(min_length=3, max_length=300)
    url: HttpUrl
    poll_interval_minutes: int = Field(default=1_440, ge=15, le=43_200)


class RegulatorySourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    regulation_id: UUID
    name: str
    url: str
    allowed_host: str
    poll_interval_minutes: int
    enabled: bool
    last_checked_at: datetime | None
    next_check_at: datetime
    consecutive_failures: int
    last_error_code: str | None


class RegulationListItem(RegulationResponse):
    latest_version_ordinal: int | None
    latest_ingested_at: datetime | None
    total_changes: int
    monitored_sources: int


class VersionSummary(BaseModel):
    id: UUID
    regulation_id: UUID
    ordinal: int
    content_hash: str
    effective_date: date | None
    source_uri: str
    ingested_at: datetime
    section_count: int
    change_count: int


class CitationResponse(BaseModel):
    version_id: UUID
    version_ordinal: int
    page: int | None
    source_uri: str


class ChangeRegisterItem(BaseModel):
    id: UUID
    regulation_id: UUID
    source_key: str
    regulation_title: str
    jurisdiction: str
    section_key: str
    heading: str
    change_type: str
    previous_version_ordinal: int | None
    current_version_ordinal: int
    previous_page: int | None
    current_page: int | None
    detected_at: datetime


class ChangeDetail(ChangeRegisterItem):
    previous_text: str | None
    current_text: str | None
    previous_citation: CitationResponse | None
    current_citation: CitationResponse


class ObligationResponse(BaseModel):
    id: UUID
    regulation_id: UUID
    version_id: UUID
    section_id: UUID
    section_key: str
    heading: str
    text: str
    evidence_quote: str
    subject: str | None
    action: str
    modality: str
    deadline_text: str | None
    raw_confidence: float
    confidence: float
    calibration_policy_id: str
    requires_review: bool
    status: str
    extraction_method: str
    rule_ids: list[str]
    page: int | None
    source_uri: str
    version_ordinal: int
    created_at: datetime


class ObligationExtractionResponse(BaseModel):
    version_id: UUID
    created_count: int
    existing_count: int
    obligations: list[ObligationResponse]


class ClauseClassificationResponse(BaseModel):
    id: UUID
    regulation_id: UUID
    version_id: UUID
    section_id: UUID
    section_key: str
    heading: str
    text: str
    label: str
    confidence: float
    abstained: bool
    status: str
    model_id: str
    dataset_id: str
    dataset_sha256: str
    probabilities: dict[str, float]
    page: int | None
    source_uri: str
    version_ordinal: int
    created_at: datetime


class ClauseClassificationRunResponse(BaseModel):
    version_id: UUID
    created_count: int
    existing_count: int
    abstained_count: int
    classifications: list[ClauseClassificationResponse]


class CalibrationBinResponse(BaseModel):
    upper_bound: float
    calibrated_confidence: float
    training_count: int


class CalibrationPolicyResponse(BaseModel):
    policy_id: str
    dataset_id: str
    dataset_size: int
    calibration_candidate_count: int
    review_threshold: float
    minimum_precision: float
    bins: list[CalibrationBinResponse]


class SearchIndexResponse(BaseModel):
    version_id: UUID
    created_count: int
    existing_count: int
    embedding_model_id: str


class RetrievalHitResponse(BaseModel):
    section_id: UUID
    regulation_id: UUID
    version_id: UUID
    section_key: str
    heading: str
    body: str
    page: int | None
    source_uri: str
    version_ordinal: int
    score: float
    lexical_score: float
    vector_score: float
    embedding_model_id: str


class HybridSearchResponse(BaseModel):
    query: str
    result_count: int
    results: list[RetrievalHitResponse]


class ControlCreate(BaseModel):
    control_key: str = Field(min_length=2, max_length=120)
    title: str = Field(min_length=3, max_length=300)
    description: str = Field(min_length=3)
    owner: str = Field(min_length=2, max_length=200)
    evidence_requirement: str = Field(min_length=3)


class ControlResponse(BaseModel):
    id: UUID
    control_key: str
    title: str
    version_id: UUID
    ordinal: int
    description: str
    owner: str
    evidence_requirement: str


class MappingResponse(BaseModel):
    id: UUID
    obligation_id: UUID
    control_version_id: UUID
    score: float
    status: str
    explanation: dict[str, object]
    mapping_method: str


class MappingSuggestionResponse(BaseModel):
    obligation_id: UUID
    state: str
    mappings: list[MappingResponse]


class ControlMappingListItem(MappingResponse):
    control_key: str
    control_title: str


class MappingDecisionCreate(BaseModel):
    decision: str = Field(pattern=r"^(accepted|rejected|deferred|confirmed_unmapped)$")
    rationale: str = Field(min_length=3, max_length=2_000)
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=120)


class MappingDecisionResponse(BaseModel):
    id: UUID
    obligation_id: UUID
    mapping_id: UUID | None
    control_version_id: UUID | None
    decision: str
    rationale: str
    actor_id: str
    revision: int
    supersedes_id: UUID | None
    decided_at: datetime


class ReviewCandidate(ControlMappingListItem):
    decision: MappingDecisionResponse | None


class ReviewQueueItem(BaseModel):
    obligation: ObligationResponse
    regulation_key: str
    regulation_title: str
    review_state: str
    candidates: list[ReviewCandidate]
    obligation_revision: int


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItem]
    total: int
    limit: int
    offset: int


class AgentWorkflowCreate(BaseModel):
    obligation_id: UUID
    goal: str = Field(min_length=10, max_length=1_000)
    idempotency_key: str = Field(min_length=8, max_length=120)


class AgentWorkflowDecisionCreate(BaseModel):
    decision: str = Field(pattern=r"^(approved|rejected|changes_requested)$")
    rationale: str = Field(min_length=10, max_length=2_000)
    idempotency_key: str = Field(min_length=8, max_length=120)
    expected_revision: int = Field(ge=0)


class AgentWorkflowDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workflow_run_id: UUID
    decision: str
    rationale: str
    actor_id: str
    revision: int
    supersedes_id: UUID | None
    decided_at: datetime


class AgentWorkflowResponse(BaseModel):
    id: UUID
    obligation_id: UUID
    status: str
    risk_level: str
    goal: str
    plan: dict[str, object]
    evidence: dict[str, object]
    proposal: dict[str, object]
    policy_results: dict[str, bool]
    agent_version: str
    evaluation_score: float
    created_by: str
    created_at: datetime
    decided_at: datetime | None
    revision: int
    latest_decision: AgentWorkflowDecisionResponse | None
    created: bool = True
