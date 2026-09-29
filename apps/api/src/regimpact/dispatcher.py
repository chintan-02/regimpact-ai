"""Publishes transactional-outbox events to the asynchronous worker queue."""

import argparse
import time

from .database import SessionFactory
from .outbox import publish_pending


def run_once() -> int:
    """Publish one outbox batch and return the number successfully published."""
    with SessionFactory() as session, session.begin():
        return publish_pending(session)


def drain_pending(*, max_batches: int = 20) -> int:
    """Drain bounded outbox batches for a one-shot cloud job execution."""
    total = 0
    for _ in range(max_batches):
        published = run_once()
        total += published
        if published == 0:
            break
    return total


def run_forever() -> None:
    """Local/development loop retained for Docker Compose and manual operation."""
    while True:
        published = run_once()
        if published == 0:
            time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="RegImpact transactional-outbox dispatcher")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Drain bounded pending outbox batches and exit; intended for scheduled cloud jobs.",
    )
    args = parser.parse_args()
    if args.once:
        drain_pending()
        return
    run_forever()


if __name__ == "__main__":
    main()
