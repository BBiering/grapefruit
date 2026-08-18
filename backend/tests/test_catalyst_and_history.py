from contextlib import contextmanager

from grapefruit import catalyst, storage
from grapefruit.pipelines.evaluate_predictions import classify_outcome


def test_agent_json_parser_accepts_fenced_json():
    parsed = catalyst._parse_json_response('before\n```json\n{"detected": true}\n```\nafter')
    assert parsed == {"detected": True}


def test_agent_json_parser_rejects_invalid_json():
    assert catalyst._parse_json_response("not json") == {}
    assert catalyst._parse_json_response("```json\n{broken}\n```") == {}


def test_prediction_outcome_classification():
    assert classify_outcome(20.0, 12.0) == "occurred"
    assert classify_outcome(20.0, -2.0) == "missed"
    assert classify_outcome(20.0, 4.0) == "unclear"
    assert classify_outcome(None, 15.0) == "unclear"


def test_event_history_upsert_does_not_delete_previous_rows(monkeypatch):
    calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def executemany(self, query, params):
            calls.append((query, list(params)))

    class Connection:
        def cursor(self):
            return Cursor()

    @contextmanager
    def fake_conn():
        yield Connection()

    monkeypatch.setattr(storage, "_conn", fake_conn)
    stored = storage.replace_forward_catalysts([
        {"symbol": "ABVX.PA", "detected": True, "event_name": "Trial", "expected_window": "2026-10-01"},
        {"symbol": "BLC.PA", "detected": False, "event_name": None},
    ])

    assert stored == 1
    assert len(calls) == 1
    assert "DELETE FROM forward_catalysts" not in calls[0][0]
    assert "ON CONFLICT (symbol, event_name, expected_window)" in calls[0][0]
    assert calls[0][1][0][0] == "ABVX.PA"
