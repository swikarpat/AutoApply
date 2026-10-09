"""Unit tests for the Telemetry Collector module."""

import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest

from src.core.telemetry import (
    collect_metrics,
    get_network_io,
    run_telemetry_loop,
)
import telemetry_collector


def test_get_network_io_initial():
    """Initial network call without previous snapshot should return 0.0 rates."""
    current_net, sent_rate, recv_rate = get_network_io(prev_net=None, elapsed=0.0)
    assert sent_rate == 0.0
    assert recv_rate == 0.0
    assert hasattr(current_net, "bytes_sent")
    assert hasattr(current_net, "bytes_recv")


def test_get_network_io_rate_calculation():
    """Rate calculation computes (diff / elapsed) correctly."""
    prev = MagicMock()
    prev.bytes_sent = 1000
    prev.bytes_recv = 2000

    current = MagicMock()
    current.bytes_sent = 6000
    current.bytes_recv = 12000

    # Mock psutil.net_io_counters to return 'current'
    import psutil
    original_fn = psutil.net_io_counters
    try:
        psutil.net_io_counters = MagicMock(return_value=current)
        _, sent_rate, recv_rate = get_network_io(prev_net=prev, elapsed=2.0)
        assert sent_rate == (6000 - 1000) / 2.0  # 2500.0
        assert recv_rate == (12000 - 2000) / 2.0  # 5000.0
    finally:
        psutil.net_io_counters = original_fn


def test_collect_metrics_structure():
    """Verify metrics dictionary adheres to the required telemetry schema."""
    metrics, current_net = collect_metrics(prev_net=None, elapsed_time=1.0)

    assert "timestamp" in metrics
    assert "cpu" in metrics
    assert "memory" in metrics
    assert "disk" in metrics
    assert "network" in metrics

    # CPU schema
    assert "total_percent" in metrics["cpu"]
    assert "per_core_percent" in metrics["cpu"]
    assert isinstance(metrics["cpu"]["per_core_percent"], list)

    # Memory schema
    mem = metrics["memory"]
    for key in ("total_bytes", "available_bytes", "used_bytes", "percent_used", "swap_used_percent"):
        assert key in mem
        assert mem[key] >= 0

    # Disk schema
    disk = metrics["disk"]
    for key in ("total_bytes", "used_bytes", "free_bytes", "percent_used", "read_count", "write_count"):
        assert key in disk
        assert disk[key] >= 0

    # Network schema
    net = metrics["network"]
    for key in ("bytes_sent_per_sec", "bytes_recv_per_sec", "total_bytes_sent", "total_bytes_recv"):
        assert key in net
        assert net[key] >= 0


def test_run_telemetry_loop_writes_jsonl():
    """Verify run_telemetry_loop appends valid JSON Lines."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "telemetry_test.jsonl")
        run_telemetry_loop(log_file=log_path, interval_seconds=0.05, max_samples=2)

        assert os.path.exists(log_path)
        with open(log_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        assert len(lines) == 2
        for line in lines:
            data = json.loads(line)
            assert "timestamp" in data
            assert "cpu" in data
            assert "memory" in data
            assert "disk" in data
            assert "network" in data


def test_root_telemetry_collector_module():
    """Verify root telemetry_collector.py exports matching functions and runs."""
    assert hasattr(telemetry_collector, "collect_metrics")
    assert hasattr(telemetry_collector, "get_network_io")
    assert hasattr(telemetry_collector, "main")

    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "collector_test.jsonl")
        telemetry_collector.main(log_file=log_path, interval_seconds=0.05, max_samples=1)
        assert os.path.exists(log_path)
