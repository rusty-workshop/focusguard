from datetime import datetime

from focusguard.common.config import Config, Profile, Schedule
from focusguard.daemon import scheduler
from focusguard.daemon.state import ManualBlock, RuntimeState


def _dt(weekday_offset_from_monday: int, hour: int, minute: int) -> datetime:
    # 2024-01-01 was a Monday.
    base = datetime(2024, 1, 1 + weekday_offset_from_monday, hour, minute)
    return base


def test_simple_same_day_window():
    sched = Schedule(enabled=True, days=[0, 1, 2, 3, 4], start="08:00", end="15:00")
    assert scheduler.schedule_matches(sched, _dt(0, 8, 0))  # exact start, Monday
    assert scheduler.schedule_matches(sched, _dt(0, 12, 30))
    assert not scheduler.schedule_matches(sched, _dt(0, 15, 0))  # end is exclusive
    assert not scheduler.schedule_matches(sched, _dt(0, 7, 59))
    assert not scheduler.schedule_matches(sched, _dt(5, 10, 0))  # Saturday not in days


def test_disabled_schedule_never_matches():
    sched = Schedule(enabled=False, days=[0], start="00:00", end="23:59")
    assert not scheduler.schedule_matches(sched, _dt(0, 12, 0))


def test_zero_length_window_never_matches():
    sched = Schedule(enabled=True, days=list(range(7)), start="10:00", end="10:00")
    assert not scheduler.schedule_matches(sched, _dt(0, 10, 0))


def test_midnight_crossing_window():
    # Bedtime-style: 22:00 Sunday -> 06:00 Monday, "days" = the day it *starts* on.
    sched = Schedule(enabled=True, days=[6], start="22:00", end="06:00")  # Sunday=6
    assert scheduler.schedule_matches(sched, _dt(6, 23, 30))  # Sunday night
    assert scheduler.schedule_matches(sched, _dt(0, 3, 0))  # Monday early morning
    assert not scheduler.schedule_matches(sched, _dt(0, 7, 0))  # past end
    assert not scheduler.schedule_matches(sched, _dt(1, 23, 30))  # Tuesday, not scheduled


def test_schedule_window_end_same_day():
    sched = Schedule(enabled=True, days=[0], start="08:00", end="15:00")
    now = _dt(0, 10, 0)
    end_ts = scheduler.schedule_window_end(sched, now)
    end_dt = datetime.fromtimestamp(end_ts)
    assert (end_dt.hour, end_dt.minute, end_dt.day) == (15, 0, now.day)


def test_schedule_window_end_midnight_crossing():
    sched = Schedule(enabled=True, days=[6], start="22:00", end="06:00")
    now = _dt(6, 23, 0)  # Sunday night, before midnight
    end_ts = scheduler.schedule_window_end(sched, now)
    end_dt = datetime.fromtimestamp(end_ts)
    assert (end_dt.hour, end_dt.minute) == (6, 0)
    assert end_dt.day == now.day + 1


def test_multiple_profiles_union_blocked_apps():
    cfg = Config()
    cfg.profiles["School"] = Profile(
        name="School", blocked_apps=["discord.desktop"],
        schedule=Schedule(enabled=True, days=[0], start="00:00", end="23:59"),
    )
    cfg.profiles["Gaming"] = Profile(
        name="Gaming", blocked_apps=["steam.desktop"],
        schedule=Schedule(enabled=True, days=[0], start="00:00", end="23:59"),
    )
    status = scheduler.compute_status(cfg, RuntimeState(), now=_dt(0, 12, 0).timestamp())
    assert set(status.blocked_desktop_ids) == {"discord.desktop", "steam.desktop"}
    assert len(status.profiles) == 2


def test_manual_block_active_outside_schedule():
    cfg = Config()
    cfg.profiles["Study"] = Profile(name="Study", blocked_apps=["spotify.desktop"])  # no schedule
    now = _dt(0, 12, 0).timestamp()
    state = RuntimeState(manual_blocks=[ManualBlock(profile="Study", started_at=now, ends_at=now + 60)])
    status = scheduler.compute_status(cfg, state, now=now)
    assert status.blocked_desktop_ids == ["spotify.desktop"]


def test_pause_suppresses_all_enforcement_but_keeps_state():
    cfg = Config()
    cfg.profiles["Study"] = Profile(name="Study", blocked_apps=["spotify.desktop"])
    now = _dt(0, 12, 0).timestamp()
    state = RuntimeState(
        manual_blocks=[ManualBlock(profile="Study", started_at=now, ends_at=now + 60)],
        paused_until=now + 30,
    )
    status = scheduler.compute_status(cfg, state, now=now)
    assert status.paused is True
    assert status.blocked_desktop_ids == []

    # after the pause expires, the underlying manual block resumes on its own
    later = now + 31
    status2 = scheduler.compute_status(cfg, state, now=later)
    assert status2.paused is False
    assert status2.blocked_desktop_ids == ["spotify.desktop"]


def test_stop_suppresses_schedule_until_window_end_only():
    cfg = Config()
    cfg.profiles["School"] = Profile(
        name="School", blocked_apps=["discord.desktop"],
        schedule=Schedule(enabled=True, days=[0], start="08:00", end="15:00"),
    )
    now_dt = _dt(0, 10, 0)
    now = now_dt.timestamp()
    suppress_until = scheduler.schedule_window_end(cfg.profiles["School"].schedule, now_dt)
    state = RuntimeState(schedule_suppressed={"School": suppress_until})

    status = scheduler.compute_status(cfg, state, now=now)
    assert status.blocked_desktop_ids == []  # suppressed for today's window

    tomorrow = _dt(7, 10, 0).timestamp()  # next Monday, same time
    status2 = scheduler.compute_status(cfg, state, now=tomorrow)
    assert status2.blocked_desktop_ids == ["discord.desktop"]  # resumes next week
