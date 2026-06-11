import sqlite3

import pytest

import net_retry
import sync_menus as sm
import sync_schedule as ss


# ---------------------------
# with_retry
# ---------------------------
def test_returns_value_after_transient_failures(monkeypatch):
    monkeypatch.setattr(net_retry.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("connection reset")
        return "data"

    assert net_retry.with_retry(flaky) == "data"
    assert calls["n"] == 3


def test_raises_last_error_when_all_attempts_fail(monkeypatch):
    monkeypatch.setattr(net_retry.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def broken():
        calls["n"] += 1
        raise OSError("down")

    with pytest.raises(OSError):
        net_retry.with_retry(broken)
    assert calls["n"] == 3


def test_backs_off_between_attempts(monkeypatch):
    slept = []
    monkeypatch.setattr(net_retry.time, "sleep", slept.append)

    def broken():
        raise OSError("down")

    with pytest.raises(OSError):
        net_retry.with_retry(broken)
    assert slept == [2, 5]


# ---------------------------
# sync scripts use it
# ---------------------------
def test_sync_menus_main_survives_one_fetch_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(net_retry.time, "sleep", lambda s: None)
    monkeypatch.setattr(sm, "DB_PATH", str(tmp_path / "t.db"))
    calls = {"n": 0}

    def flaky_fetch():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("connection reset")
        return {"fields": {}}

    monkeypatch.setattr(sm, "fetch_menu_doc", flaky_fetch)
    sm.main()  # must not raise
    assert calls["n"] == 2


def test_sync_schedule_main_survives_one_fetch_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(net_retry.time, "sleep", lambda s: None)
    db = tmp_path / "t.db"
    sqlite3.connect(db).execute(
        "CREATE TABLE ScheduleTimeline (sched_date TEXT, item_type TEXT, "
        "block_code TEXT, start_time TEXT, end_time TEXT, item_order INTEGER)"
    ).connection.commit()
    monkeypatch.setattr(ss, "DB_PATH", str(db))
    monkeypatch.setenv("MSM_ICAL_URL", "https://example.test/feed.ics")
    calls = {"n": 0}

    def flaky_fetch(source):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("connection reset")
        return ""

    monkeypatch.setattr(ss, "fetch_ical", flaky_fetch)
    ss.main()  # must not raise
    assert calls["n"] == 2
