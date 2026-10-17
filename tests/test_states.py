from app.core.states import (
    BUCKET_OFFLINE,
    BUCKET_ONLINE,
    BUCKET_SLEEPING,
    BUCKET_TRANSITIONAL,
    BUCKET_UNKNOWN,
    bucket_of,
    state_name,
)


def test_known_state_names():
    assert state_name(20) == "Ready"
    assert state_name(50) == "Sleeping"
    assert state_name(0) == "Stopped"
    assert state_name(100) == "Failed"


def test_unknown_state_name_fallback():
    assert state_name(1234) == "Unknown(1234)"
    assert state_name(None) == "Unknown"


def test_buckets():
    assert bucket_of(20) == BUCKET_ONLINE
    assert bucket_of(50) == BUCKET_SLEEPING
    assert bucket_of(45) == BUCKET_SLEEPING
    assert bucket_of(0) == BUCKET_OFFLINE
    assert bucket_of(100) == BUCKET_OFFLINE
    for transitional in (5, 7, 10, 30, 40, 60, 70, 75):
        assert bucket_of(transitional) == BUCKET_TRANSITIONAL
    assert bucket_of(None) == BUCKET_UNKNOWN
    assert bucket_of(1234) == BUCKET_UNKNOWN
