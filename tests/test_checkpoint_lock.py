import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from src.core.notifier import (
    alert_checkpoint_detected,
    create_checkpoint_lock,
    is_checkpoint_locked,
    clear_checkpoint_lock,
)
from src.agents.discovery_agent import DiscoveryAgent


def test_alert_checkpoint_detected_sound():
    with patch("src.core.notifier.send_macos_notification") as mock_send:
        mock_send.return_value = True
        success = alert_checkpoint_detected(url="https://www.linkedin.com/checkpoint/test")
        assert success is True
        assert mock_send.called
        kwargs = mock_send.call_args[1]
        assert kwargs["sound"] == "Sosumi"
        assert "Security Checkpoint" in kwargs["title"]


def test_lockfile_lifecycle(tmp_path):
    test_lock = os.path.join(tmp_path, ".checkpoint_lock")

    # 1. Initially unlocked
    locked, data = is_checkpoint_locked(test_lock)
    assert locked is False
    assert data is None

    # 2. Create lockfile
    created_path = create_checkpoint_lock(
        url="https://www.linkedin.com/checkpoint/challenge/123",
        reason="Arkose Labs challenge",
        lock_path=test_lock
    )
    assert created_path == test_lock
    assert os.path.exists(test_lock)

    # 3. Read lockfile
    locked, data = is_checkpoint_locked(test_lock)
    assert locked is True
    assert data is not None
    assert "timestamp" in data
    assert data["url"] == "https://www.linkedin.com/checkpoint/challenge/123"
    assert data["reason"] == "Arkose Labs challenge"

    # 4. Clear lockfile
    cleared = clear_checkpoint_lock(test_lock)
    assert cleared is True
    assert not os.path.exists(test_lock)

    # 5. Clear again (already cleared)
    cleared_again = clear_checkpoint_lock(test_lock)
    assert cleared_again is False


@pytest.mark.asyncio
async def test_detect_security_checkpoint_url():
    mock_store = MagicMock()
    mock_browser = MagicMock()
    mock_llm = MagicMock()
    agent = DiscoveryAgent(mock_store, mock_browser, mock_llm)

    # A. Checkpoint URL detected
    page = MagicMock()
    page.url = "https://www.linkedin.com/checkpoint/challenge/I289d0"
    page.evaluate = AsyncMock(return_value={"detected": False, "reason": ""})

    detected, reason = await agent.detect_security_checkpoint(page)
    assert detected is True
    assert "Security challenge URL detected" in reason

    # B. Normal job URL
    page.url = "https://www.linkedin.com/jobs/view/4429707612/"
    detected, reason = await agent.detect_security_checkpoint(page)
    assert detected is False
    assert reason == ""


@pytest.mark.asyncio
async def test_detect_security_checkpoint_dom():
    mock_store = MagicMock()
    mock_browser = MagicMock()
    mock_llm = MagicMock()
    agent = DiscoveryAgent(mock_store, mock_browser, mock_llm)

    page = MagicMock()
    page.url = "https://www.linkedin.com/feed/"

    # Arkose Labs iframe found in DOM
    page.evaluate = AsyncMock(return_value={"detected": True, "reason": "Arkose Labs / CAPTCHA iframe found in DOM"})
    detected, reason = await agent.detect_security_checkpoint(page)
    assert detected is True
    assert "Arkose Labs" in reason

    # Normal DOM
    page.evaluate = AsyncMock(return_value={"detected": False, "reason": ""})
    detected, reason = await agent.detect_security_checkpoint(page)
    assert detected is False
