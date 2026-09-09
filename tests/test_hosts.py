import pytest

from focusguard.daemon.hosts import MARK_BEGIN, MARK_END, merge_into_hosts, render_managed_block


def test_render_empty_domains_is_empty_string():
    assert render_managed_block([]) == ""


def test_render_includes_www_variant_and_markers():
    block = render_managed_block(["reddit.com"])
    assert block.startswith(MARK_BEGIN + "\n")
    assert block.endswith(MARK_END + "\n")
    assert "0.0.0.0 reddit.com" in block
    assert "0.0.0.0 www.reddit.com" in block


def test_render_is_sorted_and_deduplicated():
    block = render_managed_block(["b.com", "a.com", "a.com"])
    a_pos = block.index("a.com")
    b_pos = block.index("b.com")
    assert a_pos < b_pos


def test_merge_appends_block_to_untouched_file():
    original = "127.0.0.1 localhost\n"
    merged = merge_into_hosts(original, ["reddit.com"])
    assert merged.startswith(original)
    assert MARK_BEGIN in merged
    assert "0.0.0.0 reddit.com" in merged


def test_merge_appends_without_double_blank_line_when_no_trailing_newline():
    original = "127.0.0.1 localhost"
    merged = merge_into_hosts(original, ["reddit.com"])
    assert "\n\n" not in merged


def test_merge_is_idempotent_and_replaces_previous_block():
    original = "127.0.0.1 localhost\n"
    once = merge_into_hosts(original, ["reddit.com"])
    twice = merge_into_hosts(once, ["reddit.com"])
    assert once == twice
    assert once.count(MARK_BEGIN) == 1


def test_merge_updates_domain_set_in_place():
    original = "127.0.0.1 localhost\n"
    with_reddit = merge_into_hosts(original, ["reddit.com"])
    with_twitter = merge_into_hosts(with_reddit, ["twitter.com"])
    assert "reddit.com" not in with_twitter
    assert "twitter.com" in with_twitter
    assert with_twitter.count(MARK_BEGIN) == 1


def test_merge_with_empty_domains_removes_block_and_preserves_rest():
    original = "127.0.0.1 localhost\n"
    with_block = merge_into_hosts(original, ["reddit.com"])
    cleared = merge_into_hosts(with_block, [])
    assert MARK_BEGIN not in cleared
    assert "127.0.0.1 localhost" in cleared


def test_merge_preserves_content_around_block():
    original = "# before\n127.0.0.1 localhost\n"
    with_block = merge_into_hosts(original, ["reddit.com"])
    with_block += "# after, added by something else\n"
    updated = merge_into_hosts(with_block, ["twitter.com"])
    assert "# before" in updated
    assert "# after, added by something else" in updated
    assert "twitter.com" in updated
    assert "reddit.com" not in updated


def test_merge_refuses_inconsistent_markers():
    broken = f"{MARK_BEGIN}\n0.0.0.0 reddit.com\n"  # BEGIN with no END
    with pytest.raises(ValueError):
        merge_into_hosts(broken, ["reddit.com"])


def test_merge_refuses_duplicate_begin_markers():
    broken = f"{MARK_BEGIN}\n{MARK_BEGIN}\n{MARK_END}\n"
    with pytest.raises(ValueError):
        merge_into_hosts(broken, ["reddit.com"])
