import pytest
from datetime import datetime, date
from unittest.mock import MagicMock
from src.core.human_pacing import HumanPacingEngine


@pytest.fixture
def sample_settings():
    return {
        "pacing": {
            "enabled": True,
            "active_start_hour": 9,
            "active_end_hour": 21,
            "active_end_minute": 30,
            "min_daily_target": 16,
            "max_daily_target": 38,
            "weekend_min_target": 6,
            "weekend_max_target": 14,
            "hard_24h_cap": 45,
        }
    }


def test_deterministic_daily_target(sample_settings):
    mock_store = MagicMock()
    engine = HumanPacingEngine(sample_settings, mock_store)

    d1 = date(2026, 10, 9)  # Friday (weekday)
    target_a = engine.get_todays_target(d1)
    target_b = engine.get_todays_target(d1)
    assert target_a == target_b
    assert 16 <= target_a <= 38


def test_weekday_quota_clamping(sample_settings):
    mock_store = MagicMock()
    engine = HumanPacingEngine(sample_settings, mock_store)

    # Test across multiple weekdays in a month
    for day in range(1, 28):
        test_d = date(2026, 10, day)
        if test_d.weekday() < 5:  # Monday to Friday
            target = engine.get_todays_target(test_d)
            assert 16 <= target <= 38, f"Weekday target {target} out of bounds for {test_d}"


def test_weekend_quota_clamping(sample_settings):
    mock_store = MagicMock()
    engine = HumanPacingEngine(sample_settings, mock_store)

    # 2026-10-10 is Saturday, 2026-10-11 is Sunday
    sat = date(2026, 10, 10)
    sun = date(2026, 10, 11)

    sat_target = engine.get_todays_target(sat)
    sun_target = engine.get_todays_target(sun)

    assert 6 <= sat_target <= 14, f"Saturday target {sat_target} out of bounds"
    assert 6 <= sun_target <= 14, f"Sunday target {sun_target} out of bounds"


def test_active_operating_hours(sample_settings):
    mock_store = MagicMock()
    engine = HumanPacingEngine(sample_settings, mock_store)

    # Inside window (09:00 - 21:30)
    assert engine.is_within_active_hours(datetime(2026, 10, 9, 9, 0, 0)) is True
    assert engine.is_within_active_hours(datetime(2026, 10, 9, 14, 30, 0)) is True
    assert engine.is_within_active_hours(datetime(2026, 10, 9, 21, 30, 0)) is True

    # Outside window
    assert engine.is_within_active_hours(datetime(2026, 10, 9, 8, 59, 59)) is False
    assert engine.is_within_active_hours(datetime(2026, 10, 9, 21, 30, 1)) is False
    assert engine.is_within_active_hours(datetime(2026, 10, 9, 23, 0, 0)) is False
    assert engine.is_within_active_hours(datetime(2026, 10, 9, 4, 0, 0)) is False


def test_can_apply_now_guardrails(sample_settings):
    mock_store = MagicMock()
    engine = HumanPacingEngine(sample_settings, mock_store)

    weekday_date = datetime(2026, 10, 9, 12, 0, 0)
    todays_target = engine.get_todays_target(weekday_date.date())

    # 1. Below target -> allowed
    mock_store.count_recent_submissions.return_value = todays_target - 5
    can_apply, reason = engine.can_apply_now(weekday_date)
    assert can_apply is True
    assert "Eligible" in reason

    # 2. At or above stochastic daily target -> blocked
    mock_store.count_recent_submissions.return_value = todays_target
    can_apply, reason = engine.can_apply_now(weekday_date)
    assert can_apply is False
    assert "daily quota reached" in reason

    # 3. At or above hard 24h cap (45) -> blocked
    mock_store.count_recent_submissions.return_value = 45
    can_apply, reason = engine.can_apply_now(weekday_date)
    assert can_apply is False
    assert "Hard 24-hour application ceiling reached" in reason

    # 4. Outside active hours -> blocked
    late_night = datetime(2026, 10, 9, 23, 15, 0)
    mock_store.count_recent_submissions.return_value = 0
    can_apply, reason = engine.can_apply_now(late_night)
    assert can_apply is False
    assert "Outside natural operating hours" in reason


def test_delay_ranges(sample_settings):
    mock_store = MagicMock()
    engine = HumanPacingEngine(sample_settings, mock_store)

    for _ in range(50):
        reading_delay = engine.get_reading_delay()
        assert 12.0 <= reading_delay <= 28.0

        step_delay = engine.get_step_delay()
        assert 1.8 <= step_delay <= 3.8

        inter_delay = engine.get_inter_job_delay()
        assert (45.0 <= inter_delay <= 110.0) or (360.0 <= inter_delay <= 720.0)
