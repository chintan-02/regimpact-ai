"""Offline external-identity bootstrap and cutover-preflight commands."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from .config import get_settings
from .database import SessionFactory
from .external_identity_operations import (
    BOOTSTRAP_ACKNOWLEDGEMENT,
    BOOTSTRAP_ROLLBACK_ACKNOWLEDGEMENT,
    ROLLBACK_ACKNOWLEDGEMENT,
    ExternalIdentityOperationError,
    bootstrap_first_admin_mapping,
    rollback_bootstrap_mapping,
    validate_cutover_readiness,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Entra cutover prerequisites offline.")
    commands = parser.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser(
        "bootstrap",
        help="Create the first Entra mapping for one existing active local administrator.",
    )
    bootstrap.add_argument("--user-id", required=True)
    bootstrap.add_argument("--entra-oid", required=True)
    bootstrap.add_argument("--acknowledge", required=True)
    rollback = commands.add_parser(
        "rollback-bootstrap",
        help="Disable only an active mapping created by this bootstrap command.",
    )
    rollback.add_argument("--mapping-id", required=True)
    rollback.add_argument("--acknowledge", required=True)
    preflight = commands.add_parser(
        "preflight",
        help="Validate Entra cutover readiness without modifying data or contacting Entra.",
    )
    preflight.add_argument("--acknowledge-legacy-rollback", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        user_id = UUID(arguments.user_id) if arguments.command == "bootstrap" else None
        external_oid = UUID(arguments.entra_oid) if arguments.command == "bootstrap" else None
        mapping_id = (
            UUID(arguments.mapping_id)
            if arguments.command == "rollback-bootstrap"
            else None
        )
    except ValueError:
        print("External identity operation failed: invalid_identifier", file=sys.stderr)
        return 2
    try:
        settings = get_settings()
    except ValueError:
        print("External identity operation failed: configuration_invalid", file=sys.stderr)
        return 2
    try:
        with SessionFactory() as session:
            if arguments.command == "bootstrap":
                assert user_id is not None and external_oid is not None
                mapping = bootstrap_first_admin_mapping(
                    session,
                    settings,
                    user_id=user_id,
                    external_oid=external_oid,
                    acknowledgement=arguments.acknowledge,
                )
                print(f"Bootstrap mapping created: mapping_id={mapping.id} user_id={mapping.user_id}")
            elif arguments.command == "rollback-bootstrap":
                assert mapping_id is not None
                mapping = rollback_bootstrap_mapping(
                    session,
                    settings,
                    mapping_id=mapping_id,
                    acknowledgement=arguments.acknowledge,
                )
                print(
                    "Bootstrap mapping disabled: "
                    f"mapping_id={mapping.id} user_id={mapping.user_id}"
                )
            else:
                result = validate_cutover_readiness(
                    session,
                    settings,
                    rollback_acknowledgement=arguments.acknowledge_legacy_rollback,
                )
                print(
                    "Cutover preflight passed: "
                    f"revision={result.migration_revision} "
                    f"active_mappings={result.active_mapping_count} "
                    f"active_admin_mappings={result.active_admin_mapping_count}"
                )
    except ExternalIdentityOperationError as exc:
        print(f"External identity operation failed: {exc.category}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("External identity operation failed: database_operation_failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BOOTSTRAP_ACKNOWLEDGEMENT",
    "BOOTSTRAP_ROLLBACK_ACKNOWLEDGEMENT",
    "ROLLBACK_ACKNOWLEDGEMENT",
    "main",
]
