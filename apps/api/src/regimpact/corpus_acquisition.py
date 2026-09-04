"""Fail-closed acquisition contracts for the governed regulatory corpus."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
_RAW_HOST = "raw.githubusercontent.com"
_SOURCE_REPOSITORY = "justicecanada/laws-lois-xml"


class CorpusAcquisitionError(RuntimeError):
    """Raised when a corpus manifest or acquired artifact fails closed."""


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    source_id: str
    document_id: str
    title: str
    regulator: str
    document_type: str
    official_url: str
    portfolio_basis_url: str
    artifact_url: str
    repository_commit: str
    rights_status: str
    rights_basis_url: str

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.source_id):
            raise ValueError("source_id must be filesystem-safe")
        if not all(
            value.strip()
            for value in (self.document_id, self.title, self.regulator, self.document_type)
        ):
            raise ValueError("document identity fields are required")
        if self.document_type not in {"act", "regulation"}:
            raise ValueError("document_type must be act or regulation")
        if self.rights_status != "review_required":
            raise ValueError("new corpus sources must remain review_required")
        if not _COMMIT.fullmatch(self.repository_commit):
            raise ValueError("repository_commit must be a full lowercase commit SHA")
        for value in (self.official_url, self.portfolio_basis_url, self.rights_basis_url):
            if urlparse(value).scheme != "https":
                raise ValueError("source evidence URLs must use HTTPS")
        _validate_artifact_url(self.artifact_url, self.repository_commit)


def _validate_artifact_url(url: str, commit: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != _RAW_HOST:
        raise ValueError("artifact_url must use raw.githubusercontent.com over HTTPS")
    parts = PurePosixPath(parsed.path).parts
    if len(parts) != 7 or parts[1:3] != ("justicecanada", "laws-lois-xml"):
        raise ValueError("artifact_url must target the Justice Canada XML repository")
    if parts[3] != commit or parts[4] != "eng" or parts[5] not in {"acts", "regulations"}:
        raise ValueError("artifact_url must contain the pinned commit and supported path")
    if not parts[6].endswith(".xml") or parsed.query or parsed.fragment:
        raise ValueError("artifact_url must identify one immutable XML file")


def load_corpus_manifest(path: Path) -> tuple[CorpusDocument, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "regimpact-corpus-manifest-v1":
        raise CorpusAcquisitionError("unsupported corpus manifest schema")
    documents = tuple(CorpusDocument(**item) for item in payload.get("documents", []))
    if len(documents) != 25:
        raise CorpusAcquisitionError("v0.6C-1 corpus must contain exactly 25 documents")
    if len({item.source_id for item in documents}) != len(documents):
        raise CorpusAcquisitionError("duplicate source_id in corpus manifest")
    if len({item.document_id for item in documents}) != len(documents):
        raise CorpusAcquisitionError("duplicate document_id in corpus manifest")
    if len({item.regulator for item in documents}) < 3:
        raise CorpusAcquisitionError("corpus must cover at least three regulators")
    if len({item.repository_commit for item in documents}) != 1:
        raise CorpusAcquisitionError("all corpus artifacts must use one repository snapshot")
    return documents


def verify_acquisition_lock(
    documents: tuple[CorpusDocument, ...], lock_path: Path
) -> dict[str, object]:
    """Verify checked-in hash evidence covers the selected snapshot exactly."""
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "regimpact-corpus-acquisition-v1":
        raise CorpusAcquisitionError("unsupported acquisition lock schema")
    if payload.get("status") != "acquired_pending_rights_review":
        raise CorpusAcquisitionError("acquisition lock has an invalid governance status")
    if payload.get("training_authorized") is not False:
        raise CorpusAcquisitionError("acquisition lock must not authorize training")
    if payload.get("repository_commit") != documents[0].repository_commit:
        raise CorpusAcquisitionError("acquisition lock repository commit mismatch")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise CorpusAcquisitionError("acquisition lock artifacts must be an array")
    by_source = {item.get("source_id"): item for item in artifacts}
    if set(by_source) != {item.source_id for item in documents} or len(by_source) != len(artifacts):
        raise CorpusAcquisitionError("acquisition lock does not exactly cover the manifest")
    for document in documents:
        artifact = by_source[document.source_id]
        if artifact.get("document_id") != document.document_id:
            raise CorpusAcquisitionError(f"locked document mismatch: {document.source_id}")
        if not _SHA256.fullmatch(str(artifact.get("artifact_sha256", ""))):
            raise CorpusAcquisitionError(f"invalid locked SHA-256: {document.source_id}")
        size = artifact.get("artifact_size_bytes")
        if not isinstance(size, int) or size <= 0:
            raise CorpusAcquisitionError(f"invalid locked artifact size: {document.source_id}")
    return payload


def _download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "RegImpact-AI-corpus-acquisition/1.0"})
    with urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise CorpusAcquisitionError(f"source returned HTTP {response.status}")
        return response.read()


def acquire_corpus(
    documents: tuple[CorpusDocument, ...],
    *,
    output_dir: Path,
    fetch: Callable[[str], bytes] = _download,
    acquired_at: datetime | None = None,
) -> dict[str, object]:
    """Download immutable XML bytes and emit non-approval acquisition evidence."""
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for document in documents:
        target = output_dir / f"{document.source_id}.xml"
        if target.exists():
            raise CorpusAcquisitionError(f"refusing to overwrite artifact: {target.name}")
        content = fetch(document.artifact_url)
        xml_probe = content.removeprefix(b"\xef\xbb\xbf").lstrip()
        if not xml_probe.startswith(b"<?xml"):
            raise CorpusAcquisitionError(f"source is not XML: {document.source_id}")
        target.write_bytes(content)
        records.append(
            {
                **asdict(document),
                "artifact_path": target.name,
                "artifact_sha256": sha256(content).hexdigest(),
                "artifact_size_bytes": len(content),
            }
        )
    timestamp = (acquired_at or datetime.now(UTC)).isoformat()
    return {
        "schema_version": "regimpact-corpus-acquisition-v1",
        "status": "acquired_pending_rights_review",
        "acquired_at": timestamp,
        "documents": len(records),
        "regulators": len({item.regulator for item in documents}),
        "repository": _SOURCE_REPOSITORY,
        "repository_commit": documents[0].repository_commit,
        "human_rights_review_required": True,
        "training_authorized": False,
        "artifacts": records,
    }
