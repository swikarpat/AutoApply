import os
from unittest.mock import patch
from src.core.notifier import send_macos_notification, notify_daily_cap_reached


def test_send_macos_notification_mock():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        success = send_macos_notification(
            title="AutoApply Test",
            message="Test message",
            subtitle="Subtitle",
            sound="Glass"
        )
        assert success is True
        assert mock_run.called
        args = mock_run.call_args[0][0]
        assert "osascript" in args
        assert "display notification" in args[2]


def test_notify_daily_cap_reached_deduplication(tmp_path):
    test_state_file = os.path.join(tmp_path, ".last_cap_alert")

    with patch("src.core.notifier.send_macos_notification") as mock_notify:
        mock_notify.return_value = True

        # 1. First trigger today -> should send notification
        first_result = notify_daily_cap_reached(
            current_count=28,
            target_quota=28,
            hard_cap=45,
            state_file=test_state_file
        )
        assert first_result is True
        assert mock_notify.call_count == 1
        assert os.path.exists(test_state_file)

        # 2. Second trigger on the same date -> should be deduplicated (False)
        second_result = notify_daily_cap_reached(
            current_count=28,
            target_quota=28,
            hard_cap=45,
            state_file=test_state_file
        )
        assert second_result is False
        assert mock_notify.call_count == 1  # Not called again

        # 3. Forced trigger -> should send notification regardless
        forced_result = notify_daily_cap_reached(
            current_count=28,
            target_quota=28,
            hard_cap=45,
            state_file=test_state_file,
            force=True
        )
        assert forced_result is True
        assert mock_notify.call_count == 2
