import pytest

from focusguard.common.config import Config, ConfigError, Profile, Schedule, load_config, save_config


def test_default_round_trip(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config()
    cfg.profiles["School"] = Profile(
        name="School",
        blocked_apps=["discord.desktop", "steam.desktop"],
        schedule=Schedule(enabled=True, days=[0, 1, 2, 3, 4], start="08:00", end="15:00"),
        manual_duration_minutes=45,
    )
    save_config(cfg, path)

    loaded = load_config(path)
    assert loaded.profiles["School"].blocked_apps == ["discord.desktop", "steam.desktop"]
    assert loaded.profiles["School"].schedule.days == [0, 1, 2, 3, 4]
    assert loaded.profiles["School"].manual_duration_minutes == 45


def test_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "does-not-exist.json")
    assert cfg.profiles == {}


def test_malformed_json_raises_and_does_not_touch_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    with pytest.raises(ConfigError):
        load_config(path)
    # file must be untouched, not truncated/replaced
    assert path.read_text() == "{not json"


def test_invalid_schedule_time_rejected():
    with pytest.raises(ConfigError):
        Config.from_dict(
            {
                "profiles": {
                    "Bad": {
                        "name": "Bad",
                        "blocked_apps": [],
                        "schedule": {"enabled": True, "days": [0], "start": "25:00", "end": "10:00"},
                    }
                }
            }
        )


def test_invalid_day_rejected():
    with pytest.raises(ConfigError):
        Config.from_dict(
            {"profiles": {"Bad": {"name": "Bad", "schedule": {"days": [7]}}}}
        )


def test_duplicate_blocked_apps_rejected():
    with pytest.raises(ConfigError):
        Config.from_dict(
            {
                "profiles": {
                    "Dup": {"name": "Dup", "blocked_apps": ["a.desktop", "a.desktop"]}
                }
            }
        )


def test_profile_key_name_mismatch_rejected():
    with pytest.raises(ConfigError):
        Config.from_dict({"profiles": {"KeyA": {"name": "OtherName"}}})


def test_atomic_save_does_not_leave_temp_files(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(), path)
    leftovers = list(tmp_path.glob(".config-*.tmp"))
    assert leftovers == []


def test_save_rejects_invalid_config(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(), path)
    before = path.read_text()

    cfg = Config()
    cfg.profiles["Bad"] = Profile(name="WrongKeyName")
    with pytest.raises(Exception):
        # constructing with mismatched dict key vs profile.name
        bad = Config(profiles={"Bad": Profile(name="Bad", manual_duration_minutes=99999)})
        save_config(bad, path)
    # original file must survive an invalid save attempt
    assert path.read_text() == before
