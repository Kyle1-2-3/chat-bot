import app as appmod
import set_up_db


def test_fetch_dorm_signins_includes_note(tmp_path, monkeypatch):
    db = tmp_path / "school.db"
    monkeypatch.setattr(set_up_db, "DB_PATH", str(db))
    monkeypatch.chdir(tmp_path)
    set_up_db.init_db()
    monkeypatch.setattr(appmod, "DB_PATH", str(db))

    rows = appmod.fetch_dorm_signins(7)  # Sunday
    morning = [r for r in rows if r["start_time"] is None]
    assert morning, "expected an untimed morning sign-in row"
    assert all("morning" in r["note"].lower() for r in morning)
    # timed rows still carry their clock time and no note
    timed = [r for r in rows if r["start_time"] is not None]
    assert {r["start_time"] for r in timed} == {"20:45", "21:15"}
