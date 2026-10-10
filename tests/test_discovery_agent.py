import pytest
from src.agents.discovery_agent import DiscoveryAgent


def test_company_size_filter_sub_5000_rejections():
    agent = DiscoveryAgent(None, None, None)
    
    # Sub-5000 employee tiers must be rejected
    rejected_cases = [
        "1-10 employees",
        "11-50 employees",
        "51-200 employees",
        "201-500 employees",
        "501-1,000 employees",
        "501-1000 employees",
        "1,001-5,000 employees",
        "1001-5000 employees",
        "company size: 1,001-5,000 employees · software development",
        "about the company: 500 employees",
        "1,200 employees",
        "4,999 employees"
    ]
    for text in rejected_cases:
        is_ok, reason = agent.check_company_size(text, min_employees=5000)
        assert not is_ok, f"Expected '{text}' to be rejected, but passed: {reason}"


def test_company_size_filter_ge_5000_acceptance():
    agent = DiscoveryAgent(None, None, None)

    # >= 5000 employee tiers must be accepted
    accepted_cases = [
        "10,001+ employees",
        "10001+ employees",
        "5,001-10,000 employees",
        "5001-10000 employees",
        "company size: 10,001+ employees · financial services",
        "10k+ employees",
        "5k-10k employees",
        "5,000+ employees",
        "7,500 employees",
        "25,000 employees",
        "140,000 employees"
    ]
    for text in accepted_cases:
        is_ok, reason = agent.check_company_size(text, min_employees=5000)
        assert is_ok, f"Expected '{text}' to be accepted, but failed: {reason}"


def test_company_size_filter_unverified_rejection():
    agent = DiscoveryAgent(None, None, None)

    # Missing or unverified company size must be rejected when min_employees is enforced
    unverified_cases = [
        "looking for a software engineer",
        "salary $180,000 - $220,000",
        "remote, united states",
        ""
    ]
    for text in unverified_cases:
        is_ok, reason = agent.check_company_size(text, min_employees=5000)
        assert not is_ok, f"Expected '{text}' without size info to be rejected, but passed: {reason}"


def test_is_california_location():
    agent = DiscoveryAgent(None, None, None)

    # California locations should return True
    ca_locations = [
        "San Francisco, CA",
        "San Jose, CA",
        "San Francisco Bay Area",
        "Bay Area, California",
        "Los Angeles, CA",
        "San Diego, CA",
        "Irvine, CA",
        "Sacramento, CA",
        "Mountain View, CA",
        "Palo Alto, CA",
        "Sunnyvale, CA",
        "California, United States",
        "Remote in California",
    ]
    for loc in ca_locations:
        assert agent.is_california_location(loc) is True, f"Expected '{loc}' to be recognized as California"

    # Non-California locations should return False
    non_ca_locations = [
        "Seattle, WA",
        "New York, NY",
        "Remote",
        "Remote, United States",
        "United States",
        "Austin, TX",
        "Chicago, IL",
        "Boston, MA",
        "Cambridge, MA",
        "Canada",
        "North Carolina",
        "South Carolina",
    ]
    for loc in non_ca_locations:
        assert agent.is_california_location(loc) is False, f"Expected '{loc}' to NOT be recognized as California"


def test_location_policy_exclude_ca():
    agent = DiscoveryAgent(None, None, None)
    settings = {"location": {"california_policy": "exclude_ca"}}

    # exclude_ca rejects both San Francisco and Los Angeles
    is_ok_sf, reason_sf = agent.evaluate_location_policy("San Francisco, CA", settings)
    assert is_ok_sf is False
    assert "Excluded Region" in reason_sf

    is_ok_la, reason_la = agent.evaluate_location_policy("Los Angeles, CA", settings)
    assert is_ok_la is False
    assert "Excluded Region" in reason_la

    # Non-CA roles remain accepted
    for non_ca in ["Seattle, WA", "New York, NY", "Remote"]:
        is_ok, reason = agent.evaluate_location_policy(non_ca, settings)
        assert is_ok is True, f"Expected non-CA '{non_ca}' to be accepted under exclude_ca: {reason}"
        assert "Non-California" in reason


def test_location_policy_bay_area_only():
    agent = DiscoveryAgent(None, None, None)
    settings = {"location": {"california_policy": "bay_area_only"}}

    # Accepts Bay Area roles
    bay_area_cases = [
        "San Francisco, CA",
        "San Jose, CA",
        "San Francisco Bay Area",
        "Sunnyvale, CA",
        "Mountain View, CA",
        "Palo Alto, CA",
        "Santa Clara, CA",
    ]
    for loc in bay_area_cases:
        is_ok, reason = agent.evaluate_location_policy(loc, settings)
        assert is_ok is True, f"Expected Bay Area location '{loc}' to be accepted: {reason}"
        assert "Accepted: Bay Area" in reason

    # Rejects non-Bay Area California roles
    non_bay_cases = [
        "Los Angeles, CA",
        "San Diego, CA",
        "Irvine, CA",
        "Sacramento, CA",
    ]
    for loc in non_bay_cases:
        is_ok, reason = agent.evaluate_location_policy(loc, settings)
        assert is_ok is False, f"Expected non-Bay Area CA location '{loc}' to be rejected"
        assert reason == "Non-Bay Area California location"

    # Non-CA roles remain accepted
    for non_ca in ["Seattle, WA", "New York, NY", "Remote"]:
        is_ok, reason = agent.evaluate_location_policy(non_ca, settings)
        assert is_ok is True, f"Expected non-CA '{non_ca}' to be accepted under bay_area_only: {reason}"
        assert "Non-California" in reason


def test_location_policy_backward_compatibility():
    agent = DiscoveryAgent(None, None, None)

    # Legacy exclude_california: true should behave as exclude_ca
    legacy_exclude_settings = {"job_search": {"exclude_california": True}}
    is_ok_sf, _ = agent.evaluate_location_policy("San Francisco, CA", legacy_exclude_settings)
    assert is_ok_sf is False

    is_ok_seattle, _ = agent.evaluate_location_policy("Seattle, WA", legacy_exclude_settings)
    assert is_ok_seattle is True

    # Legacy exclude_california: false should behave as all_ca
    legacy_include_settings = {"job_search": {"exclude_california": False}}
    is_ok_sf_inc, _ = agent.evaluate_location_policy("San Francisco, CA", legacy_include_settings)
    assert is_ok_sf_inc is True

    is_ok_la_inc, _ = agent.evaluate_location_policy("Los Angeles, CA", legacy_include_settings)
    assert is_ok_la_inc is True


def test_location_policy_all_ca():
    agent = DiscoveryAgent(None, None, None)
    settings = {"location": {"california_policy": "all_ca"}}

    for loc in ["San Francisco, CA", "Los Angeles, CA", "San Diego, CA", "Seattle, WA", "Remote"]:
        is_ok, reason = agent.evaluate_location_policy(loc, settings)
        assert is_ok is True, f"Expected '{loc}' to be accepted under all_ca: {reason}"


def test_location_policy_default_no_filtering():
    """When no location policy is specified, all locations across US are accepted without post-filtering."""
    agent = DiscoveryAgent(None, None, None)
    default_settings = {
        "job_search": {
            "target_location": "United States",
            "target_titles": ["Staff Software Engineer"]
        }
    }

    all_locations = [
        "San Francisco, CA",
        "Los Angeles, CA",
        "San Diego, CA",
        "Campbell, CA",
        "Milpitas, CA",
        "Seattle, WA",
        "Austin, TX",
        "New York, NY",
        "Chicago, IL",
        "Remote",
    ]
    for loc in all_locations:
        is_ok, reason = agent.evaluate_location_policy(loc, default_settings)
        assert is_ok is True, f"Expected '{loc}' to be accepted without filtering: {reason}"
        assert "accepted" in reason.lower()

    # Empty settings should also accept everything
    for loc in all_locations:
        is_ok, reason = agent.evaluate_location_policy(loc, {})
        assert is_ok is True


def test_build_search_url_location():
    agent = DiscoveryAgent(None, None, None)

    # 1. Default to United States
    url_default = agent.build_search_url({
        "job_search": {
            "target_titles": ["Software Engineer"],
            "target_location": "United States",
        }
    })
    assert "location=United+States" in url_default

    # 2. California Only scope
    url_ca = agent.build_search_url({
        "job_search": {
            "target_titles": ["Software Engineer"],
            "target_location": "California",
        }
    })
    assert "location=California" in url_ca


