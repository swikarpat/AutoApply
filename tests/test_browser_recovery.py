"""Unit tests for browser recovery, stale lock cleanup, and disconnect detection."""

import os
import tempfile
import pytest
from playwright.async_api import Error as PlaywrightError

from src.mcp.tools.browser import (
    StealthBrowserTool,
    TargetClosedError,
    is_browser_disconnected_error,
)


def test_cleanup_stale_locks():
    """Verify that stale Chromium Singleton files are cleanly unlinked."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create dummy Singleton files
        lock_file = os.path.join(tmpdir, "SingletonLock")
        cookie_file = os.path.join(tmpdir, "SingletonCookie")
        socket_file = os.path.join(tmpdir, "SingletonSocket")

        with open(lock_file, "w") as f:
            f.write("test_lock")
        with open(cookie_file, "w") as f:
            f.write("test_cookie")
        with open(socket_file, "w") as f:
            f.write("test_socket")

        assert os.path.exists(lock_file)
        assert os.path.exists(cookie_file)
        assert os.path.exists(socket_file)

        tool = StealthBrowserTool(headless=True, user_data_dir=tmpdir)
        tool.cleanup_stale_locks()

        assert not os.path.exists(lock_file)
        assert not os.path.exists(cookie_file)
        assert not os.path.exists(socket_file)


def test_is_browser_disconnected_error():
    """Verify detection of various disconnect / lid close error messages."""
    # Target closed error
    err1 = TargetClosedError("Target page, context or browser has been closed")
    assert is_browser_disconnected_error(err1) is True

    # Playwright Error with connection closed message
    err2 = PlaywrightError("Connection closed while reading from socket")
    assert is_browser_disconnected_error(err2) is True

    # Playwright Error with browser closed
    err3 = PlaywrightError("Browser closed unexpectedly")
    assert is_browser_disconnected_error(err3) is True

    # Unrelated Playwright error (e.g. selector timeout)
    err4 = PlaywrightError("Timeout 30000ms exceeded waiting for locator")
    assert is_browser_disconnected_error(err4) is False

    # Standard non-playwright exception
    err5 = ValueError("Value error")
    assert is_browser_disconnected_error(err5) is False
