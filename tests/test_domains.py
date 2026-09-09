import pytest

from focusguard.common.domains import (
    InvalidDomainError,
    hosts_names_for,
    normalize_domain,
    validate_domain,
)


def test_normalize_strips_scheme_path_and_trailing_dot():
    assert normalize_domain("https://Reddit.com/r/all") == "reddit.com"
    assert normalize_domain("reddit.com.") == "reddit.com"
    assert normalize_domain("  reddit.com  ") == "reddit.com"


def test_normalize_strips_port():
    assert normalize_domain("example.com:8080") == "example.com"


def test_normalize_accepts_subdomain():
    assert normalize_domain("www.reddit.com") == "www.reddit.com"


@pytest.mark.parametrize("bad", ["", "not a domain", "no-dot", "-bad.com", "bad-.com", "a..b.com", "http://"])
def test_normalize_rejects_garbage(bad):
    with pytest.raises(InvalidDomainError):
        normalize_domain(bad)


def test_validate_domain_accepts_normalized_form():
    validate_domain("reddit.com")  # no raise


def test_validate_domain_rejects_url():
    with pytest.raises(InvalidDomainError):
        validate_domain("https://reddit.com")


def test_hosts_names_adds_www_variant():
    assert hosts_names_for("reddit.com") == ["reddit.com", "www.reddit.com"]


def test_hosts_names_does_not_double_www():
    assert hosts_names_for("www.reddit.com") == ["www.reddit.com"]
