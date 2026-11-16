"""Offline operator commands for companion client grants."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from .companion_grant_operations import (
    CHANGE_ACKNOWLEDGEMENT,
    DISABLE_ACKNOWLEDGEMENT,
    GRANT_ACKNOWLEDGEMENT,
    CompanionGrantOperationError,
    change_companion_grant_scopes,
    create_companion_grant,
    disable_companion_grant,
)
from .config import get_settings
from .database import SessionFactory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage companion client grants offline.")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    change = commands.add_parser("change-scopes")
    disable = commands.add_parser("disable")
    for command in (create, change, disable):
        command.add_argument("--admin-user-id", required=True)
        command.add_argument("--acknowledge", required=True)
    for command in (create, change):
        command.add_argument("--scope", action="append", required=True)
    change.add_argument("--grant-id", required=True)
    disable.add_argument("--grant-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        admin_user_id = UUID(arguments.admin_user_id)
        grant_id = UUID(arguments.grant_id) if hasattr(arguments, "grant_id") else None
        settings = get_settings()
        with SessionFactory() as session:
            if arguments.command == "create":
                grant = create_companion_grant(
                    session,
                    settings,
                    admin_user_id=admin_user_id,
                    scopes=tuple(arguments.scope),
                    acknowledgement=arguments.acknowledge,
                )
                message = "created"
            elif arguments.command == "change-scopes":
                assert grant_id is not None
                grant = change_companion_grant_scopes(
                    session,
                    grant_id=grant_id,
                    admin_user_id=admin_user_id,
                    scopes=tuple(arguments.scope),
                    acknowledgement=arguments.acknowledge,
                )
                message = "updated"
            else:
                assert grant_id is not None
                grant = disable_companion_grant(
                    session,
                    grant_id=grant_id,
                    admin_user_id=admin_user_id,
                    acknowledgement=arguments.acknowledge,
                )
                message = "disabled"
        print(f"Companion client grant {message}: grant_id={grant.id}")
        return 0
    except (ValueError, CompanionGrantOperationError) as exc:
        category = exc.category if isinstance(exc, CompanionGrantOperationError) else "invalid_identifier"
        print(f"Companion client grant operation failed: {category}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("Companion client grant operation failed: database_operation_failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CHANGE_ACKNOWLEDGEMENT",
    "DISABLE_ACKNOWLEDGEMENT",
    "GRANT_ACKNOWLEDGEMENT",
    "main",
]
