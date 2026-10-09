import os
import subprocess
from datetime import datetime
from typing import Optional


def send_macos_notification(
    title: str,
    message: str,
    subtitle: str = "",
    sound: str = "Glass"
) -> bool:
    """
    Triggers a native macOS desktop banner notification with audio chime via osascript.
    Returns True if successfully dispatched, False otherwise.
    """
    try:
        # Escape double quotes to avoid shell/AppleScript injection
        safe_title = title.replace('"', '\\"')
        safe_msg = message.replace('"', '\\"')
        safe_subtitle = subtitle.replace('"', '\\"')

        script_parts = [f'display notification "{safe_msg}" with title "{safe_title}"']
        if safe_subtitle:
            script_parts.append(f'subtitle "{safe_subtitle}"')
        if sound:
            script_parts.append(f'sound name "{sound}"')

        apple_script = " ".join(script_parts)
        res = subprocess.run(
            ["osascript", "-e", apple_script],
            capture_output=True,
            text=True,
            check=False,
            timeout=5
        )
        return res.returncode == 0
    except Exception as e:
        print(f"  [Notification Warning] Could not dispatch macOS notification: {e}")
        return False


def notify_daily_cap_reached(
    current_count: int,
    target_quota: int,
    hard_cap: int,
    reason: str = "",
    state_file: str = "data/.last_cap_alert",
    sound: str = "Glass",
    force: bool = False
) -> bool:
    """
    Notifies the user via macOS Desktop Banner when the daily quota or hard 24h cap is reached.
    Maintains date deduplication so the user receives exactly ONE chime per calendar day.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Deduplicate alerts per day unless force is True
    if not force and os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                last_alert_date = f.read().strip()
            if last_alert_date == today_str:
                return False  # Already alerted today
        except Exception:
            pass

    title = "AutoApply: Daily Cap Reached"
    subtitle = f"🎯 Quota Hit ({current_count}/{target_quota} apps)"
    message = (
        f"Completed {current_count} applications. "
        f"Daily quota of {target_quota} reached (Hard cap: {hard_cap}). "
        f"AutoApply is resting safely until tomorrow."
    )

    success = send_macos_notification(
        title=title,
        message=message,
        subtitle=subtitle,
        sound=sound
    )

    if success or not os.path.exists(state_file):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(state_file)), exist_ok=True)
            with open(state_file, "w", encoding="utf-8") as f:
                f.write(today_str)
        except Exception:
            pass

    return success
