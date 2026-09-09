from focusguard.common.blocklists import STARTER_BLOCKLISTS
from focusguard.common.domains import validate_domain


def test_all_starter_domains_are_valid_and_normalized():
    for category, domains in STARTER_BLOCKLISTS.items():
        assert domains, f"{category} must not be empty"
        for domain in domains:
            validate_domain(domain)  # raises if not already normalized
            assert domain == domain.lower()


def test_no_duplicate_domains_within_a_category():
    for category, domains in STARTER_BLOCKLISTS.items():
        assert len(domains) == len(set(domains)), f"{category} has duplicates"


def test_category_names_are_unique():
    names = list(STARTER_BLOCKLISTS.keys())
    assert len(names) == len(set(names))
