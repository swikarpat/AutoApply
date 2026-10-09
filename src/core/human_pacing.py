import random
from datetime import datetime, date, time
from typing import Optional, Tuple
from src.core.database import ApplicationStateStore


class HumanPacingEngine:
    """
    Human Behavioral Mimicry and Anti-Bot Pacing Engine.
    Enforces rolling 24-hour application caps, stochastic daily quotas,
    natural operating hours (09:00 - 21:30), and humanized micro-delays.
    """

    def __init__(self, settings: dict, store: ApplicationStateStore):
        self.settings = settings
        self.store = store
        pacing_cfg = settings.get("pacing", {})

        self.enabled = pacing_cfg.get("enabled", True)
        self.active_start_hour = pacing_cfg.get("active_start_hour", 9)
        self.active_end_hour = pacing_cfg.get("active_end_hour", 21)
        self.active_end_minute = pacing_cfg.get("active_end_minute", 30)
        self.min_daily_target = pacing_cfg.get("min_daily_target", 16)
        self.max_daily_target = pacing_cfg.get("max_daily_target", 38)
        self.weekend_min_target = pacing_cfg.get("weekend_min_target", 6)
        self.weekend_max_target = pacing_cfg.get("weekend_max_target", 14)
        self.hard_24h_cap = pacing_cfg.get("hard_24h_cap", 45)

    def get_todays_target(self, target_date: Optional[date] = None) -> int:
        """
        Dynamically calculates a deterministic floating daily target seeded by the calendar date.
        - Weekdays (Mon-Fri): Gaussian distribution clamped between min and max target (mean 26, std 5).
        - Weekends (Sat-Sun): Reduced volume between weekend_min and weekend_max target.
        """
        if target_date is None:
            target_date = datetime.now().date()

        # Seed deterministically with the calendar date's ordinal number
        rng = random.Random(target_date.toordinal())

        # Weekday check (0=Mon, 4=Fri, 5=Sat, 6=Sun)
        if target_date.weekday() < 5:
            val = rng.gauss(26.0, 5.0)
            clamped = int(round(max(self.min_daily_target, min(self.max_daily_target, val))))
            return clamped
        else:
            return rng.randint(self.weekend_min_target, self.weekend_max_target)

    def is_within_active_hours(self, now_dt: Optional[datetime] = None) -> bool:
        """Checks if the given or current local time is within natural operating hours (09:00 - 21:30)."""
        if not self.enabled:
            return True

        if now_dt is None:
            now_dt = datetime.now()

        start_time = time(self.active_start_hour, 0, 0)
        end_time = time(self.active_end_hour, self.active_end_minute, 0)
        return start_time <= now_dt.time() <= end_time

    def can_apply_now(self, now_dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Evaluates whether an application can be safely submitted right now:
        1. Checks natural operating hours (09:00 - 21:30).
        2. Checks rolling 24-hour application count against hard 24h cap (e.g. 45).
        3. Checks rolling 24-hour application count against stochastic daily quota.
        """
        if not self.enabled:
            return True, "Pacing engine is disabled"

        if now_dt is None:
            now_dt = datetime.now()

        # 1. Operating hours check
        if not self.is_within_active_hours(now_dt):
            return False, (
                f"Outside natural operating hours "
                f"({self.active_start_hour:02d}:00 - {self.active_end_hour:02d}:{self.active_end_minute:02d} local time)"
            )

        # 2. Rolling 24-hour count
        count_24h = self.store.count_recent_submissions(24)

        # Hard 24h ceiling
        if count_24h >= self.hard_24h_cap:
            return False, f"Hard 24-hour application ceiling reached ({count_24h}/{self.hard_24h_cap})"

        # 3. Stochastic daily quota check
        todays_target = self.get_todays_target(now_dt.date())
        if count_24h >= todays_target:
            return False, f"Stochastic daily quota reached ({count_24h}/{todays_target} for {now_dt.date()})"

        return True, f"Eligible to apply ({count_24h}/{todays_target} submitted in rolling 24h, hard cap: {self.hard_24h_cap})"

    def get_reading_delay(self) -> float:
        """Returns realistic job description reading delay before clicking Easy Apply (12 to 28 seconds)."""
        return round(random.uniform(12.0, 28.0), 2)

    def get_step_delay(self) -> float:
        """Returns realistic transition delay between application modal steps (1.8 to 3.8 seconds)."""
        return round(random.uniform(1.8, 3.8), 2)

    def get_inter_job_delay(self) -> float:
        """
        Returns realistic inter-application delay:
        - 45 to 110 seconds normally.
        - 15% probability of an extended 6 to 12 minute break (360 to 720 seconds).
        """
        if random.random() < 0.15:
            return round(random.uniform(360.0, 720.0), 2)
        return round(random.uniform(45.0, 110.0), 2)
