from unittest.mock import MagicMock, patch

from regimpact import dispatcher, scheduler


def test_scheduler_run_once_claims_due_sources() -> None:
    factory = MagicMock()
    session = factory.return_value.__enter__.return_value
    session.begin.return_value.__enter__.return_value = None
    session.begin.return_value.__exit__.return_value = None

    with patch.object(scheduler, "SessionFactory", factory), patch.object(
        scheduler, "claim_due_sources", return_value=3
    ) as claim:
        assert scheduler.run_once() == 3

    claim.assert_called_once_with(session)


def test_dispatcher_run_once_publishes_one_batch() -> None:
    factory = MagicMock()
    session = factory.return_value.__enter__.return_value
    session.begin.return_value.__enter__.return_value = None
    session.begin.return_value.__exit__.return_value = None

    with patch.object(dispatcher, "SessionFactory", factory), patch.object(
        dispatcher, "publish_pending", return_value=7
    ) as publish:
        assert dispatcher.run_once() == 7

    publish.assert_called_once_with(session)


def test_dispatcher_drain_pending_is_bounded_and_stops_when_empty() -> None:
    with patch.object(dispatcher, "run_once", side_effect=[100, 2, 0]) as run_once:
        assert dispatcher.drain_pending(max_batches=20) == 102

    assert run_once.call_count == 3


def test_dispatcher_drain_pending_honors_batch_bound() -> None:
    with patch.object(dispatcher, "run_once", return_value=100) as run_once:
        assert dispatcher.drain_pending(max_batches=2) == 200

    assert run_once.call_count == 2
