"""Tests for app/scoring domain helpers."""
from app.scoring import compute_score, compute_accuracy, group_by_type


def test_compute_score_empty():
    assert compute_score([]) == 0


def test_compute_score_weights():
    entities = [
        {"type": "email", "confidence": "high"},
        {"type": "url", "confidence": "low"},
    ]
    # base: 3+1=4, variety: 2 types * 2 = 4 → total 8
    assert compute_score(entities) == 8


def test_compute_accuracy_empty():
    assert compute_accuracy([]) == 0


def test_compute_accuracy_all_high():
    entities = [{"type": "email", "confidence": "high"}, {"type": "url", "confidence": "high"}]
    assert compute_accuracy(entities) == 90


def test_group_by_type_url_before_email():
    entities = [
        {"type": "email", "value": "a@b.com", "confidence": "high"},
        {"type": "url", "value": "http://x.com", "confidence": "medium"},
    ]
    keys = list(group_by_type(entities).keys())
    assert keys.index("url") < keys.index("email")
