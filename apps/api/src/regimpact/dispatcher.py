"""Small process that drains the outbox; one or more replicas are safe."""

import time

from .database import SessionFactory
from .outbox import publish_pending


def run_forever() -> None:
    while True:
        with SessionFactory() as session, session.begin():
            published = publish_pending(session)
        if published == 0:
            time.sleep(1)


if __name__ == "__main__":
    run_forever()
