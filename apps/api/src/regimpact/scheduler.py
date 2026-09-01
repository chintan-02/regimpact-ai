"""Claims due regulatory sources and writes dispatch events transactionally."""

import time

from .database import SessionFactory
from .source_monitor import claim_due_sources


def run_forever() -> None:
    while True:
        with SessionFactory() as session, session.begin():
            claimed = claim_due_sources(session)
        time.sleep(5 if claimed else 30)


if __name__ == "__main__":
    run_forever()
