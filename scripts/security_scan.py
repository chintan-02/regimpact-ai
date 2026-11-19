"""Fail-closed repository scan for forbidden artifacts and common credential patterns."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess  # nosec B404
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_MAX_SCANNED_BYTES = 1_000_000
_PRIVATE_SUFFIXES = frozenset({".key", ".p12", ".pfx", ".jks"})
_PRIVATE_KEY_NAMES = frozenset({"id_dsa", "id_ecdsa", "id_ed25519", "id_rsa"})
_PLACEHOLDER_VALUES = frozenset(
    {
        "",
        "changeme",
        "example",
        "false",
        "none",
        "placeholder",
        "redacted",
        "test",
        "true",
    }
)
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key_material", re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b")),
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:export\s+)?"
    r"([A-Z][A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API_KEY|PRIVATE_KEY)[A-Z0-9_]*)"
    r"\s*=\s*[\"']?([^\"'\s#]+)"
)


@dataclass(frozen=True)
class Finding:
    """A non-sensitive description of one repository policy violation."""

    path: str
    line: int
    category: str
    fingerprint: str


def _finding(path: PurePosixPath, line: int, category: str, evidence: str) -> Finding:
    fingerprint = hashlib.sha256(
        f"regimpact-secret-scan-v1\0{path}\0{category}\0{evidence}".encode()
    ).hexdigest()
    return Finding(str(path), line, category, fingerprint)


def is_forbidden_artifact(path: PurePosixPath) -> bool:
    """Return whether a repository path represents forbidden secret-bearing material."""

    name = path.name.lower()
    if name == ".env.example":
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    return name in _PRIVATE_KEY_NAMES or path.suffix.lower() in _PRIVATE_SUFFIXES


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    return (
        normalized in _PLACEHOLDER_VALUES
        or (normalized.startswith("<") and normalized.endswith(">"))
        or (normalized.startswith("${") and normalized.endswith("}"))
        or normalized.startswith(("synthetic_", "replace-"))
    )


def scan_text(path: PurePosixPath, text: str) -> list[Finding]:
    """Scan decoded text without returning or printing matched secret values."""

    findings: list[Finding] = []
    for category, pattern in _SECRET_PATTERNS:
        findings.extend(
            _finding(path, _line_number(text, match.start()), category, match.group(0))
            for match in pattern.finditer(text)
        )
    findings.extend(
        _finding(
            path,
            _line_number(text, match.start()),
            "credential_assignment",
            f"{match.group(1)}={match.group(2)}",
        )
        for match in _SECRET_ASSIGNMENT.finditer(text)
        if not _is_placeholder(match.group(2))
    )
    return findings


def candidate_paths_from_nul(data: bytes) -> tuple[PurePosixPath, ...]:
    """Decode the NUL-delimited paths emitted by ``git ls-files -z``."""

    if not data:
        return ()
    if not data.endswith(b"\0"):
        raise ValueError("candidate path input must be NUL-terminated")
    raw_paths = data[:-1].split(b"\0")
    if any(not raw_path for raw_path in raw_paths):
        raise ValueError("candidate path input contains an empty path")
    return tuple(PurePosixPath(raw_path.decode("utf-8")) for raw_path in raw_paths)


def _invalid_candidate_path(path: PurePosixPath) -> bool:
    return path.is_absolute() or ".." in path.parts or "\\" in str(path)


def _scan_content(
    relative_path: PurePosixPath,
    content: bytes,
    *,
    is_symlink: bool = False,
) -> list[Finding]:
    if is_forbidden_artifact(relative_path):
        return [_finding(relative_path, 0, "forbidden_artifact", str(relative_path))]
    if is_symlink:
        return [_finding(relative_path, 0, "unscannable_symlink", str(relative_path))]
    if len(content) > _MAX_SCANNED_BYTES:
        return [_finding(relative_path, 0, "unscannable_large_file", str(len(content)))]
    if b"\0" in content:
        return [
            _finding(relative_path, 0, "unscannable_binary_file", str(relative_path))
        ]
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return [
            _finding(relative_path, 0, "unscannable_non_utf8_file", str(relative_path))
        ]
    return scan_text(relative_path, text)


def scan_repository(
    root: Path, candidate_paths: Sequence[PurePosixPath]
) -> list[Finding]:
    """Scan the explicit working-tree candidate set and return safe findings."""

    findings: list[Finding] = []
    for relative_path in candidate_paths:
        if _invalid_candidate_path(relative_path):
            findings.append(
                _finding(relative_path, 0, "invalid_candidate_path", str(relative_path))
            )
            continue

        path = root / relative_path
        if path.is_symlink():
            findings.extend(_scan_content(relative_path, b"", is_symlink=True))
            continue
        if not path.is_file():
            findings.append(
                _finding(relative_path, 0, "missing_candidate", str(relative_path))
            )
            continue
        findings.extend(_scan_content(relative_path, path.read_bytes()))
    return findings


def scan_repository_ref(
    root: Path,
    baseline_ref: str,
    candidate_paths: Sequence[PurePosixPath],
) -> list[Finding]:
    """Scan candidate contents at a trusted Git baseline without checking out files."""

    git = "/usr/bin/git"
    # The baseline is verified as a commit and Git is invoked without a shell.
    verified = subprocess.run(  # nosec B603
        [git, "rev-parse", "--verify", f"{baseline_ref}^{{commit}}"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if verified.returncode != 0:
        raise ValueError("baseline ref is not a local commit")
    findings: list[Finding] = []
    for relative_path in candidate_paths:
        if _invalid_candidate_path(relative_path):
            continue
        listed = subprocess.run(  # nosec B603
            [
                git,
                "ls-tree",
                "-z",
                "--name-only",
                baseline_ref,
                "--",
                str(relative_path),
            ],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if listed.returncode != 0:
            raise ValueError("baseline tree cannot be read")
        if not listed.stdout:
            continue
        result = subprocess.run(  # nosec B603
            [git, "show", f"{baseline_ref}:{relative_path}"],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            raise ValueError("baseline content cannot be read")
        findings.extend(_scan_content(relative_path, result.stdout))
    return findings


def new_findings(
    current: Sequence[Finding], baseline: Sequence[Finding]
) -> list[Finding]:
    """Return findings not already present at the Git baseline, preserving duplicates."""

    known = Counter(finding.fingerprint for finding in baseline)
    result: list[Finding] = []
    for finding in current:
        if known[finding.fingerprint]:
            known[finding.fingerprint] -= 1
        else:
            result.append(finding)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Run the repository policy scan without printing matched values."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument(
        "--paths-from-stdin",
        action="store_true",
        help="read the NUL-delimited Git candidate set from standard input",
    )
    parser.add_argument(
        "--baseline-ref",
        required=True,
        help="trusted Git commit whose exact findings are accepted as the baseline",
    )
    arguments = parser.parse_args(argv)
    if not arguments.paths_from_stdin:
        parser.error("--paths-from-stdin is required")
    try:
        candidate_paths = candidate_paths_from_nul(sys.stdin.buffer.read())
    except (UnicodeDecodeError, ValueError):
        sys.stderr.write("Repository scan failed: invalid candidate path input.\n")
        return 2
    repository = arguments.repository.resolve()
    try:
        current = scan_repository(repository, candidate_paths)
        baseline = scan_repository_ref(
            repository, arguments.baseline_ref, candidate_paths
        )
    except ValueError:
        sys.stderr.write(
            "Repository scan failed: baseline is unavailable or unreadable.\n"
        )
        return 2
    findings = new_findings(current, baseline)
    if findings:
        for finding in findings:
            location = (
                f"{finding.path}:{finding.line}" if finding.line else finding.path
            )
            sys.stderr.write(f"{location}: {finding.category}\n")
        return 1
    sys.stdout.write("Repository secret and artifact scan passed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
