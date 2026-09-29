"""Claims due regulatory sources and writes dispatch events transactionally."""

import argparse
import time

from .database import SessionFactory
from .source_monitor import claim_due_sources


def run_once() -> int:
    """Claim currently due sources once and return the number claimed."""
    with SessionFactory() as session, session.begin():
        return claim_due_sources(session)


def run_forever() -> None:
    """Local/development loop retained for Docker Compose and manual operation."""
    while True:
        claimed = run_once()
        time.sleep(5 if claimed else 30)


def main() -> None:
    parser = argparse.ArgumentParser(description="RegImpact regulatory-source scheduler")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Claim due sources once and exit; intended for scheduled cloud jobs.",
    )
    args = parser.parse_args()
    if args.once:
        run_once()
        return
    run_forever()


if __name__ == "__main__":
    main()
