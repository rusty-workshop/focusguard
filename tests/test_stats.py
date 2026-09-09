from datetime import date, timedelta

from focusguard.daemon.stats import Stats


def test_add_and_read_today():
    s = Stats()
    today = date(2026, 3, 5)
    s.add_seconds(["School"], 60, today.isoformat())
    s.add_seconds(["School", "Study"], 30, today.isoformat())
    assert s.today_totals(today) == {"School": 90, "Study": 30}


def test_zero_or_negative_seconds_ignored():
    s = Stats()
    today = date(2026, 3, 5)
    s.add_seconds(["School"], 0, today.isoformat())
    s.add_seconds(["School"], -5, today.isoformat())
    assert s.today_totals(today) == {}


def test_week_totals_sum_last_seven_days_inclusive():
    s = Stats()
    today = date(2026, 3, 10)
    for offset in range(0, 10):
        day = (today - timedelta(days=offset)).isoformat()
        s.add_seconds(["School"], 10, day)
    # 7 days inclusive of today = offsets 0..6
    assert s.week_totals(today) == {"School": 70}


def test_week_totals_excludes_future_days():
    s = Stats()
    today = date(2026, 3, 10)
    s.add_seconds(["School"], 100, (today + timedelta(days=1)).isoformat())
    assert s.week_totals(today) == {}


def test_round_trip_save_and_load(tmp_path):
    path = tmp_path / "stats.json"
    s = Stats()
    today = date(2026, 3, 5)
    s.add_seconds(["School"], 42, today.isoformat())
    s.save(today=today, path=path)

    loaded = Stats.load(path=path)
    assert loaded.today_totals(today) == {"School": 42}


def test_save_prunes_entries_older_than_retention(tmp_path):
    path = tmp_path / "stats.json"
    s = Stats()
    today = date(2026, 3, 5)
    old_day = (today - timedelta(days=200)).isoformat()
    s.add_seconds(["School"], 10, old_day)
    s.add_seconds(["School"], 10, today.isoformat())
    s.save(today=today, path=path)

    loaded = Stats.load(path=path)
    assert old_day not in loaded.daily
    assert today.isoformat() in loaded.daily


def test_load_missing_file_returns_empty(tmp_path):
    s = Stats.load(path=tmp_path / "does-not-exist.json")
    assert s.daily == {}


def test_load_malformed_json_returns_empty(tmp_path):
    path = tmp_path / "stats.json"
    path.write_text("{not json")
    s = Stats.load(path=path)
    assert s.daily == {}


def test_all_time_totals_sum_across_all_retained_days():
    s = Stats()
    today = date(2026, 3, 5)
    s.add_seconds(["School"], 10, (today - timedelta(days=1)).isoformat())
    s.add_seconds(["School"], 20, today.isoformat())
    assert s.all_time_totals(today) == {"School": 30}
