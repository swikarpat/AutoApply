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
