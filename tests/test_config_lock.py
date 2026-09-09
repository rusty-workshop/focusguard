import time

from focusguard.common.config import Config, Profile
from focusguard.daemon.config_lock import apply_commitment_lock
from focusguard.daemon.state import ManualBlock, RuntimeState


def _active_profile(name="School", commitment_seconds=30, **kwargs):
    return Profile(name=name, blocked_apps=["x.desktop"], commitment_seconds=commitment_seconds, **kwargs)


def test_weakened_commitment_seconds_is_reverted_while_active():
    old_cfg = Config(profiles={"School": _active_profile(commitment_seconds=30)})
    new_cfg = Config(profiles={"School": _active_profile(commitment_seconds=0)})
    now = time.time()
    state = RuntimeState(manual_blocks=[ManualBlock(profile="School", started_at=now, ends_at=now + 3600)])

    locked_cfg, locked = apply_commitment_lock(old_cfg, new_cfg, state, now)

    assert locked == ["School"]
    assert locked_cfg.profiles["School"].commitment_seconds == 30


def test_deleting_an_active_protected_profile_is_reverted():
    old_cfg = Config(profiles={"School": _active_profile()})
    new_cfg = Config(profiles={})  # deleted entirely
    now = time.time()
    state = RuntimeState(manual_blocks=[ManualBlock(profile="School", started_at=now, ends_at=now + 3600)])

    locked_cfg, locked = apply_commitment_lock(old_cfg, new_cfg, state, now)

    assert locked == ["School"]
    assert "School" in locked_cfg.profiles
    assert locked_cfg.profiles["School"].commitment_seconds == 30


def test_removed_blocked_domain_is_reverted_while_active():
    old_cfg = Config(profiles={"School": _active_profile(blocked_domains=["reddit.com", "instagram.com"])})
    new_cfg = Config(profiles={"School": _active_profile(blocked_domains=["instagram.com"])})  # reddit removed
    now = time.time()
    state = RuntimeState(manual_blocks=[ManualBlock(profile="School", started_at=now, ends_at=now + 3600)])

    locked_cfg, locked = apply_commitment_lock(old_cfg, new_cfg, state, now)

    assert locked == ["School"]
    assert locked_cfg.profiles["School"].blocked_domains == ["reddit.com", "instagram.com"]


def test_inactive_protected_profile_is_not_locked():
    old_cfg = Config(profiles={"School": _active_profile()})  # not started -- no manual block, no schedule
    new_cfg = Config(profiles={"School": _active_profile(commitment_seconds=0)})
    state = RuntimeState()

    locked_cfg, locked = apply_commitment_lock(old_cfg, new_cfg, state)

    assert locked == []
    assert locked_cfg.profiles["School"].commitment_seconds == 0


def test_active_profile_without_commitment_is_not_locked():
    old_cfg = Config(profiles={"Study": _active_profile("Study", commitment_seconds=0)})
    new_cfg = Config(profiles={})  # freely deletable -- no commitment set
    now = time.time()
    state = RuntimeState(manual_blocks=[ManualBlock(profile="Study", started_at=now, ends_at=now + 3600)])

    locked_cfg, locked = apply_commitment_lock(old_cfg, new_cfg, state, now)

    assert locked == []
    assert "Study" not in locked_cfg.profiles


def test_edits_to_unrelated_profiles_pass_through():
    old_cfg = Config(profiles={
        "School": _active_profile("School"),
        "Gaming": Profile(name="Gaming", blocked_apps=["steam.desktop"]),
    })
    new_cfg = Config(profiles={
        "School": _active_profile("School", commitment_seconds=0),  # attempted weaken
        "Gaming": Profile(name="Gaming", blocked_apps=["steam.desktop", "discord.desktop"]),  # legit edit
    })
    now = time.time()
    state = RuntimeState(manual_blocks=[ManualBlock(profile="School", started_at=now, ends_at=now + 3600)])

    locked_cfg, locked = apply_commitment_lock(old_cfg, new_cfg, state, now)

    assert locked == ["School"]
    assert locked_cfg.profiles["School"].commitment_seconds == 30
    assert locked_cfg.profiles["Gaming"].blocked_apps == ["steam.desktop", "discord.desktop"]


def test_adding_more_restrictions_while_active_is_allowed_through():
    # apply_commitment_lock only ever reverts a protected+active profile
    # wholesale -- it doesn't try to distinguish "made it stricter" from
    # "made it looser" edits within that one profile, so even a strictly
    # additive edit is held back until the profile stops. Documented here
    # so a future change to that behavior is a deliberate decision.
    old_cfg = Config(profiles={"School": _active_profile(blocked_domains=["reddit.com"])})
    new_cfg = Config(profiles={"School": _active_profile(blocked_domains=["reddit.com", "youtube.com"])})
    now = time.time()
    state = RuntimeState(manual_blocks=[ManualBlock(profile="School", started_at=now, ends_at=now + 3600)])

    locked_cfg, locked = apply_commitment_lock(old_cfg, new_cfg, state, now)

    assert locked == ["School"]
    assert locked_cfg.profiles["School"].blocked_domains == ["reddit.com"]
