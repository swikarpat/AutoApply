#!/usr/bin/env python3
"""Telemetry Collector Script (telemetry_collector.py)

Uses psutil to continuously record system telemetry (CPU, memory, disk, and network usage)
and append the data to a JSON Lines (.jsonl) file.
"""

import argparse
import datetime
import json
import os
import sys
import time
from typing import Any, Dict, Optional, Tuple

import psutil

# Configuration Defaults
LOG_FILE = "telemetry_log.jsonl"
INTERVAL_SECONDS = 5  # Time to wait between samples


def get_network_io(
    prev_net: Optional[Any], elapsed: float
) -> Tuple[Any, float, float]:
    """Calculate network throughput (bytes sent/received per second)."""
    current_net = psutil.net_io_counters()
    if prev_net is None or elapsed <= 0:
        bytes_sent_per_sec = 0.0
        bytes_recv_per_sec = 0.0
    else:
        bytes_sent_per_sec = (current_net.bytes_sent - prev_net.bytes_sent) / elapsed
        bytes_recv_per_sec = (current_net.bytes_recv - prev_net.bytes_recv) / elapsed
    return current_net, bytes_sent_per_sec, bytes_recv_per_sec


def collect_metrics(
    prev_net: Optional[Any], elapsed_time: float
) -> Tuple[Dict[str, Any], Any]:
    """Gathers CPU, Memory, Disk, and Network telemetry."""
    # 1. CPU Metrics
    cpu_percent = psutil.cpu_percent(interval=None)
    cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)

    # 2. Memory Metrics
    # Safe retrieval supporting both virtual_memory and potential aliases
    if hasattr(psutil, "virtual_memory"):
        virtual_mem = psutil.virtual_memory()
    else:
        virtual_mem = getattr(psutil, "virtual_mem")()
    swap_mem = psutil.swap_memory()

    # 3. Disk Metrics (root partition '/' or 'C:\\' on Windows)
    disk_mount = "C:\\" if os.name == "nt" else "/"
    disk_usage = psutil.disk_usage(disk_mount)
    disk_io = psutil.disk_io_counters()

    # 4. Network Metrics
    current_net, net_sent_rate, net_recv_rate = get_network_io(prev_net, elapsed_time)

    metrics: Dict[str, Any] = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "cpu": {
            "total_percent": cpu_percent,
            "per_core_percent": cpu_per_core,
        },
        "memory": {
            "total_bytes": virtual_mem.total,
            "available_bytes": virtual_mem.available,
            "used_bytes": virtual_mem.used,
            "percent_used": virtual_mem.percent,
            "swap_used_percent": swap_mem.percent,
        },
        "disk": {
            "total_bytes": disk_usage.total,
            "used_bytes": disk_usage.used,
            "free_bytes": disk_usage.free,
            "percent_used": disk_usage.percent,
            "read_count": disk_io.read_count if disk_io else 0,
            "write_count": disk_io.write_count if disk_io else 0,
        },
        "network": {
            "bytes_sent_per_sec": round(net_sent_rate, 2),
            "bytes_recv_per_sec": round(net_recv_rate, 2),
            "total_bytes_sent": current_net.bytes_sent if current_net else 0,
            "total_bytes_recv": current_net.bytes_recv if current_net else 0,
        },
    }
    return metrics, current_net


def main(
    log_file: str = LOG_FILE,
    interval_seconds: float = INTERVAL_SECONDS,
    max_samples: Optional[int] = None,
) -> None:
    """Main execution loop for telemetry collection."""
    print("Starting telemetry collection...")
    print(f"Logging to: {log_file}")
    print(f"Sampling interval: {interval_seconds}s (Press Ctrl+C to stop)\n")

    # Prime CPU percent reading (the first call returns 0.0)
    psutil.cpu_percent(interval=None)
    last_time = time.time()
    prev_net = psutil.net_io_counters()

    parent_dir = os.path.dirname(log_file)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    samples = 0
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            while True:
                if max_samples is not None and samples >= max_samples:
                    break

                time.sleep(interval_seconds)
                now = time.time()
                elapsed = now - last_time
                metrics, prev_net = collect_metrics(prev_net, elapsed)
                last_time = now

                # Write as JSON Line and flush buffer to ensure persistence
                f.write(json.dumps(metrics) + "\n")
                f.flush()
                samples += 1

                # Print brief status to console
                net_down_kb = metrics["network"]["bytes_recv_per_sec"] / 1024
                print(
                    f"[{metrics['timestamp']}] "
                    f"CPU: {metrics['cpu']['total_percent']:>5.1f}% | "
                    f"RAM: {metrics['memory']['percent_used']:>5.1f}% | "
                    f"Disk: {metrics['disk']['percent_used']:>5.1f}% | "
                    f"Net Down: {net_down_kb:>7.1f} KB/s"
                )
    except KeyboardInterrupt:
        print("\nCollection stopped by user.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Continuously record system telemetry to a JSON Lines (.jsonl) file."
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=LOG_FILE,
        help=f"Path to JSON Lines output log file (default: {LOG_FILE})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=INTERVAL_SECONDS,
        help=f"Sampling interval in seconds (default: {INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=None,
        help="Optional maximum number of samples to collect before exiting",
    )
    args = parser.parse_args()

    main(
        log_file=args.log_file,
        interval_seconds=args.interval,
        max_samples=args.samples,
    )
