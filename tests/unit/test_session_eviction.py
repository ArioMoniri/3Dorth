"""Active sessions must survive LRU eviction (fix for volume-info 404 after churn)."""
import core.resources as R
from api.routers import session as sess


def test_touch_on_access_protects_active_session(monkeypatch):
    monkeypatch.setattr(R, "MAX_SESSIONS", 3)
    sess.SESSIONS.clear()
    try:
        for k in ("a", "b", "c"):
            sess.SESSIONS[k] = {"sides": {}}
        # The user keeps viewing 'a' (the oldest-created) — accessing it marks it
        # most-recently-used, so it must NOT be the eviction victim.
        assert sess._get_session("a") is sess.SESSIONS["a"]
        sess._evict_old_sessions()          # makes room for a new session
        sess.SESSIONS["d"] = {"sides": {}}
        assert "a" in sess.SESSIONS         # survived: it was actively used
        assert "b" not in sess.SESSIONS     # evicted: genuinely least-recently-used
        assert set(sess.SESSIONS) == {"a", "c", "d"}
    finally:
        sess.SESSIONS.clear()


def test_missing_session_raises_404_with_reload_hint():
    from fastapi import HTTPException
    import pytest
    sess.SESSIONS.pop("nope", None)
    with pytest.raises(HTTPException) as ei:
        sess._get_session("nope")
    assert ei.value.status_code == 404
    assert "reload" in ei.value.detail.lower()
