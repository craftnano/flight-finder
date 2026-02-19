import json
import os
import threading
from datetime import datetime, timezone

USAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_usage.json")
DAILY_CAP = 1000
_lock = threading.Lock()


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read_usage():
    try:
        with open(USAGE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"date": _today(), "calls": 0}


def _write_usage(data):
    with open(USAGE_FILE, "w") as f:
        json.dump(data, f)


def get_usage():
    """Return (calls_used_today, daily_cap). Resets if date changed (UTC)."""
    with _lock:
        data = _read_usage()
        if data.get("date") != _today():
            data = {"date": _today(), "calls": 0}
            _write_usage(data)
        return data["calls"], DAILY_CAP


def increment_usage(count=1):
    """Add count calls. Returns True if under cap, False if cap exceeded."""
    with _lock:
        data = _read_usage()
        if data.get("date") != _today():
            data = {"date": _today(), "calls": 0}
        if data["calls"] + count > DAILY_CAP:
            _write_usage(data)
            return False
        data["calls"] += count
        _write_usage(data)
        return True
