from __future__ import annotations

from integri_audit_tool import db


def _mock_conn(mocker):
    mock_conn = mocker.MagicMock()
    mock_cursor = mocker.MagicMock()
    mock_conn.cursor.return_value.__enter__ = mocker.Mock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = mocker.Mock(return_value=False)
    return mock_conn, mock_cursor


def test_connect_read_only_passes_connect_timeout_and_sets_read_only(mocker):
    mock_conn, _ = _mock_conn(mocker)
    mock_connect = mocker.patch.object(db.psycopg, "connect", return_value=mock_conn)

    with db.connect_read_only("postgresql://example") as conn:
        assert conn is mock_conn

    mock_connect.assert_called_once_with("postgresql://example", connect_timeout=db.CONNECT_TIMEOUT_SECONDS)
    assert mock_conn.read_only is True


def test_connect_read_only_sets_default_session_timeouts(mocker):
    mock_conn, mock_cursor = _mock_conn(mocker)
    mocker.patch.object(db.psycopg, "connect", return_value=mock_conn)

    with db.connect_read_only("postgresql://example"):
        pass

    executed = [call.args[0] for call in mock_cursor.execute.call_args_list]
    assert executed == [
        f"SET statement_timeout = {db.STATEMENT_TIMEOUT_MS}",
        f"SET lock_timeout = {db.LOCK_TIMEOUT_MS}",
        f"SET idle_in_transaction_session_timeout = {db.IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS}",
    ]


def test_connect_read_only_accepts_timeout_overrides(mocker):
    mock_conn, mock_cursor = _mock_conn(mocker)
    mock_connect = mocker.patch.object(db.psycopg, "connect", return_value=mock_conn)

    with db.connect_read_only(
        "postgresql://example",
        connect_timeout_seconds=5,
        statement_timeout_ms=1000,
        lock_timeout_ms=500,
        idle_in_transaction_session_timeout_ms=2000,
    ):
        pass

    mock_connect.assert_called_once_with("postgresql://example", connect_timeout=5)
    executed = [call.args[0] for call in mock_cursor.execute.call_args_list]
    assert executed == [
        "SET statement_timeout = 1000",
        "SET lock_timeout = 500",
        "SET idle_in_transaction_session_timeout = 2000",
    ]


def test_connect_read_only_closes_connection_on_exit(mocker):
    mock_conn, _ = _mock_conn(mocker)
    mocker.patch.object(db.psycopg, "connect", return_value=mock_conn)

    with db.connect_read_only("postgresql://example"):
        pass

    mock_conn.close.assert_called_once()
