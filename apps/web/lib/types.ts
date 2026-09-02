export type Regulation = {
  id: string;
  organization_id: string;
  source_key: string;
  title: string;
  jurisdiction: string;
  created_at: string;
  latest_version_ordinal: number | null;
  latest_ingested_at: string | null;
  total_changes: number;
  monitored_sources: number;
};

export type Change = {
  id: string;
  regulation_id: string;
  source_key: string;
  regulation_title: string;
  jurisdiction: string;
  section_key: string;
  heading: string;
  change_type: "added" | "modified" | "removed";
  previous_version_ordinal: number | null;
  current_version_ordinal: number;
  previous_page: number | null;
  current_page: number | null;
  detected_at: string;
};

export type Citation = {
  version_id: string;
  version_ordinal: number;
  page: number | null;
  source_uri: string;
};

export type ChangeDetail = Change & {
  previous_text: string | null;
  current_text: string | null;
  previous_citation: Citation | null;
  current_citation: Citation;
};

export type Source = {
  id: string;
  organization_id: string;
  regulation_id: string;
  name: string;
  url: string;
  allowed_host: string;
  poll_interval_minutes: number;
  enabled: boolean;
  last_checked_at: string | null;
  next_check_at: string;
  consecutive_failures: number;
  last_error_code: string | null;
};

export type Ingestion = {
  id: string;
  organization_id: string;
  regulation_id: string;
  status: "queued" | "processing" | "completed" | "failed" | "dead_letter";
  original_filename: string;
  media_type: string;
  size_bytes: number;
  content_hash: string;
  resulting_version_id: string | null;
  error_code: string | null;
  error_message: string | null;
  attempt_count: number;
  max_attempts: number;
  failure_class: string | null;
  next_retry_at: string | null;
  lease_expires_at: string | null;
  last_heartbeat_at: string | null;
  replay_count: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type Obligation = {
  id: string;
  regulation_id: string;
  version_id: string;
  section_id: string;
  section_key: string;
  heading: string;
  text: string;
  evidence_quote: string;
  subject: string | null;
  action: string;
  modality: string;
  deadline_text: string | null;
  raw_confidence: number;
  confidence: number;
  calibration_policy_id: string;
  requires_review: boolean;
  status: string;
  extraction_method: string;
  rule_ids: string[];
  page: number | null;
  source_uri: string;
  version_ordinal: number;
  created_at: string;
};

export type Control = {
  id: string;
  control_key: string;
  title: string;
  version_id: string;
  ordinal: number;
  description: string;
  owner: string;
  evidence_requirement: string;
};

export type ControlMapping = {
  id: string;
  obligation_id: string;
  control_version_id: string;
  control_key: string;
  control_title: string;
  score: number;
  status: "suggested" | "needs_review" | "ambiguous" | "unmapped";
  explanation: { matched_terms?: string[]; [key: string]: unknown };
  mapping_method: string;
};

export type MappingDecision = {
  id: string;
  obligation_id: string;
  mapping_id: string | null;
  control_version_id: string | null;
  decision: "accepted" | "rejected" | "deferred" | "confirmed_unmapped";
  rationale: string;
  actor_id: string;
  revision: number;
  supersedes_id: string | null;
  decided_at: string;
};

export type ReviewCandidate = ControlMapping & { decision: MappingDecision | null };

export type ReviewItem = {
  obligation: Obligation;
  regulation_key: string;
  regulation_title: string;
  review_state: string;
  candidates: ReviewCandidate[];
  obligation_revision: number;
};

export type ReviewQueue = { items: ReviewItem[]; total: number; limit: number; offset: number };

export type OperationalSnapshot = {
  generated_at: string;
  uptime_seconds: number;
  requests: { total: number; server_errors: number };
  ingestions: Record<string, number>;
  outbox_pending: number;
  outbox_dead_letter: number;
};
