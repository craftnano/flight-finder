import json
import os
import threading
from datetime import datetime, timezone

IP_LIMITS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ip_limits.json")
IP_DAILY_CAP = 10
_lock = threading.Lock()


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read_limits():
    try:
        with open(IP_LIMITS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"date": _today(), "ips": {}}


def _write_limits(data):
    with open(IP_LIMITS_FILE, "w") as f:
        json.dump(data, f)


def check_ip_limit(ip_address):
    """
    Check and increment the search count for an IP address.
    Returns True if under the daily cap, False if limit exceeded.
    Resets all counts at midnight UTC.
    """
    with _lock:
        data = _read_limits()
        if data.get("date") != _today():
            data = {"date": _today(), "ips": {}}
        count = data["ips"].get(ip_address, 0)
        if count >= IP_DAILY_CAP:
            return False
        data["ips"][ip_address] = count + 1
        _write_limits(data)
        return True


def get_ip_usage(ip_address):
    """Return (searches_used, daily_cap) for an IP address."""
    with _lock:
        data = _read_limits()
        if data.get("date") != _today():
            return 0, IP_DAILY_CAP
        return data["ips"].get(ip_address, 0), IP_DAILY_CAP
