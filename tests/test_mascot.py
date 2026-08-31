from focusguard.common import mascot


def test_nudge_includes_app_name_and_vigi_name():
    title, body = mascot.nudge_for("Discord")
    assert mascot.NAME in title
    assert "Discord" in body


def test_status_message_covers_every_known_state():
    for state in ("ACTIVE", "PAUSED", "INACTIVE"):
        msg = mascot.status_message(state)
        assert isinstance(msg, str) and msg


def test_status_message_falls_back_for_unknown_state():
    assert mascot.status_message("SOMETHING_UNEXPECTED") in mascot.STATUS_MESSAGES["INACTIVE"]


def test_nudge_message_bank_has_real_variety():
    assert len(mascot.NUDGE_MESSAGES) >= 15


def test_every_nudge_message_has_the_app_placeholder():
    for template in mascot.NUDGE_MESSAGES:
        assert "{app}" in template


def test_status_message_bank_has_multiple_options_per_state():
    for state, options in mascot.STATUS_MESSAGES.items():
        assert len(options) >= 2, f"{state} should offer some variety"


def test_asset_path_resolves_to_an_existing_file():
    path = mascot.asset_path()
    assert path is not None
    assert path.is_file()
    assert path.suffix == ".svg"
