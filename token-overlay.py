#!/usr/bin/env python3
"""
Claude Code Token Overlay - Floating widget showing token usage

Usage:
    python3 token-overlay.py          # Start overlay
    python3 token-overlay.py --mini   # Compact mode

Features:
- Displays token usage from Honeycomb API
- Manual refresh button
- Auto-refresh every 5 minutes (toggleable)
- Shows 7-day and last 30-minute usage
- Self-update from GitHub
"""

__version__ = "1.0.0"

import json
import os
import sys
import threading
import time
import tkinter as tk
import tkinter.messagebox
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import subprocess

# Configuration directory and files
CONFIG_DIR = Path.home() / ".config" / "token-overlay"
CONFIG_FILE = CONFIG_DIR / "config.json"
CACHE_FILE = CONFIG_DIR / ".token-cache.json"
CACHE_30MIN_FILE = CONFIG_DIR / ".token-cache-30min.json"
PID_FILE = CONFIG_DIR / ".pid"

# Self-update configuration
GITHUB_REPO = "choobs96/token-overlay-tool"
GITHUB_RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main"
VERSION_URL = f"{GITHUB_RAW_BASE}/VERSION"
SCRIPT_URL = f"{GITHUB_RAW_BASE}/token-overlay.py"


def load_config():
    """Load config from file or environment variables."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    config = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                config = json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")

    # Environment variable overrides
    config["api_key"] = os.getenv("HONEYCOMB_API_KEY", config.get("api_key", ""))
    config["user_email"] = os.getenv("USER_EMAIL", config.get("user_email", ""))
    config["dataset"] = config.get("dataset", "")
    config["environment"] = config.get("environment", "")
    config["refresh_interval"] = config.get("refresh_interval", 30)  # minutes

    if not config.get("api_key") or not config.get("user_email"):
        print("ERROR: Missing config. Run install.sh or set environment variables.")
        sys.exit(1)

    return config


def save_config(config: dict):
    """Save config to file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def check_pid_file():
    """Check if another instance is running."""
    if PID_FILE.exists():
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            # Check if process exists
            try:
                os.kill(old_pid, 0)
                sys.exit(0)  # Already running, exit silently
            except ProcessLookupError:
                PID_FILE.unlink()  # Stale PID file
        except (ValueError, FileNotFoundError):
            pass

    # Write current PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def cleanup_pid_file():
    """Remove PID file on exit."""
    try:
        PID_FILE.unlink()
    except:
        pass


# Load configuration
CONFIG = load_config()
HONEYCOMB_API_KEY = CONFIG["api_key"]
HONEYCOMB_DATASET = CONFIG["dataset"]
HONEYCOMB_ENVIRONMENT = CONFIG["environment"]
USER_EMAIL = CONFIG["user_email"]
REFRESH_INTERVAL = CONFIG["refresh_interval"]

# Cache TTLs (in seconds)
CACHE_TTL_MAIN = 300      # 5 min for 7-day/daily data
CACHE_TTL_30MIN = 60      # 1 min for 30-min data

# Sydney timezone
SYDNEY_TZ = ZoneInfo('Australia/Sydney')

# Model name mapping
MODEL_NAMES = {
    "global.anthropic.claude-opus-4-5-20251101-v1:0": "Opus 4.5 (Bedrock Global)",
    "global.anthropic.claude-3-5-haiku-20241022-v1:0": "Haiku 3.5 (Bedrock Global)",
    "au.anthropic.claude-haiku-4-5-20251001-v1:0": "Haiku 4.5 (Bedrock AU)",
    "au.anthropic.claude-opus-4-6-v1": "Opus 4.6 (Bedrock AU)",
    "claude-opus-4-5-20251101": "Opus 4.5 (Direct)",
    "claude-opus-4-6": "Opus 4.6 (Direct)",
    "claude-haiku-4-5-20251001": "Haiku 4.5 (Direct)",
}


def format_tokens(n: float) -> str:
    if n is None or n == 0:
        return "0"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(int(n))


def format_cost(n: float) -> str:
    if n is None or n == 0:
        return "$0"
    if n < 10:
        return f"${n:.2f}"
    return f"${n:.0f}"


def friendly_model_name(model: str) -> str:
    return MODEL_NAMES.get(model, model[:30] if model else "Unknown")


def is_cache_fresh(cache_file: Path, ttl_seconds: int) -> bool:
    """Check if cache file exists and is fresh."""
    if not cache_file.exists():
        return False
    try:
        with open(cache_file) as f:
            data = json.load(f)
        updated_at = data.get("updated_at", "")
        if not updated_at:
            return False
        cache_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        age = (datetime.now(cache_time.tzinfo) - cache_time).total_seconds()
        return age < ttl_seconds
    except:
        return False


def load_30min_cache() -> dict:
    """Load 30-min cache if fresh, else return None."""
    if not is_cache_fresh(CACHE_30MIN_FILE, CACHE_TTL_30MIN):
        return None
    try:
        with open(CACHE_30MIN_FILE) as f:
            return json.load(f)
    except:
        return None


def save_30min_cache(data: dict):
    """Save 30-min cache."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(CACHE_30MIN_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _curl_json(url: str, method: str = "GET", data: dict = None) -> dict:
    """Make an HTTP request using curl (bypasses Python SSL issues with corporate proxies)."""
    cmd = ["curl", "-s", "--max-time", "30", "-X", method, url,
           "-H", f"X-Honeycomb-Team: {HONEYCOMB_API_KEY}",
           "-H", "Content-Type: application/json"]
    if data is not None:
        cmd += ["-d", json.dumps(data)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed ({result.returncode}): {result.stderr}")
    return json.loads(result.stdout)


def _curl_text(url: str, timeout: int = 30) -> str:
    """Fetch raw text from a URL using curl."""
    cmd = ["curl", "-sfL", "--max-time", str(timeout), url]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def _parse_version(version_str: str) -> tuple:
    """Parse version string like '1.2.3' into comparable tuple."""
    try:
        return tuple(int(x) for x in version_str.strip().split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def check_for_update() -> tuple:
    """Check GitHub for a newer version. Returns (remote_version, message)."""
    try:
        remote_version = _curl_text(VERSION_URL).strip()
        local = _parse_version(__version__)
        remote = _parse_version(remote_version)
        if remote > local:
            return remote_version, f"Update available: v{__version__} → v{remote_version}"
        else:
            return None, f"Already up to date (v{__version__})"
    except Exception as e:
        return None, f"Update check failed: {e}"


def download_and_install_update() -> str:
    """Download latest version and replace the installed script. Returns status message."""
    try:
        new_script = _curl_text(SCRIPT_URL, timeout=60)

        if "class TokenOverlay" not in new_script or "__version__" not in new_script:
            return "Error: Downloaded file doesn't look like token-overlay"
        if len(new_script) < 1000:
            return "Error: Downloaded file is suspiciously small"

        install_path = Path(os.path.abspath(sys.argv[0]))

        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=install_path.parent, prefix=".token-overlay-update-"
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                f.write(new_script)
            original_mode = os.stat(install_path).st_mode
            os.chmod(tmp_path, original_mode)
            os.replace(tmp_path, str(install_path))
            return "Update installed successfully!"
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        return f"Update failed: {e}"


def query_honeycomb(time_range: str, breakdowns: list = None) -> dict:
    """Query Honeycomb API directly using 3-step process (via curl)."""
    base_url = "https://api.honeycomb.io/1"
    env_param = f"environment={HONEYCOMB_ENVIRONMENT}"

    query_spec = {
        "calculations": [
            {"op": "SUM", "column": "claude_code.token.usage"},
            {"op": "SUM", "column": "claude_code.cost.usage"},
            {"op": "COUNT"}
        ],
        "filters": [
            {"column": "user.email", "op": "=", "value": USER_EMAIL}
        ],
        "time_range": int(time_range) if time_range.isdigit() else 604800,
    }

    if breakdowns:
        query_spec["breakdowns"] = breakdowns
        query_spec["limit"] = 20

    try:
        # Step 1: Create query spec
        create_url = f"{base_url}/queries/{HONEYCOMB_DATASET}?{env_param}"
        result = _curl_json(create_url, "POST", query_spec)
        query_id = result.get("id")
        if not query_id:
            print(f"Honeycomb API: no query_id in response: {result}")
            return {}

        # Step 2: Execute query
        exec_url = f"{base_url}/query_results/{HONEYCOMB_DATASET}?{env_param}"
        exec_result = _curl_json(exec_url, "POST", {"query_id": query_id})
        result_id = exec_result.get("id")
        if not result_id:
            print(f"Honeycomb API: no result_id in response: {exec_result}")
            return {}

        # Step 3: Poll for results
        poll_url = f"{base_url}/query_results/{HONEYCOMB_DATASET}/{result_id}?{env_param}"
        for _ in range(15):
            results = _curl_json(poll_url)
            if results.get("complete"):
                return results
            time.sleep(0.3)

        return results
    except Exception as e:
        print(f"Honeycomb API error: {e}")
        return {}


def fetch_usage_from_honeycomb() -> dict:
    """Fetch 7-day usage by model from Honeycomb."""
    results = query_honeycomb("604800", ["model"])  # 7 days in seconds

    by_model = []
    totals = {"tokens": 0, "cost": 0, "events": 0}

    # Results are in data['results'][n]['data']
    data_results = results.get("data", {}).get("results", [])
    for item in data_results:
        row = item.get("data", {})
        model = row.get("model", "")
        tokens = row.get("SUM(claude_code.token.usage)", 0) or 0
        cost = row.get("SUM(claude_code.cost.usage)", 0) or 0
        events = row.get("COUNT", 0) or 0

        if model:  # Skip empty model rows for by_model list
            by_model.append({
                "model": friendly_model_name(model),
                "tokens": tokens,
                "cost": cost,
                "events": events
            })

        totals["tokens"] += tokens
        totals["cost"] += cost
        totals["events"] += events

    # Sort by tokens descending
    by_model.sort(key=lambda x: x["tokens"], reverse=True)

    return {"by_model": by_model, "totals": totals}


def fetch_30min_usage() -> dict:
    """Fetch last 30 minutes usage from Honeycomb."""
    results = query_honeycomb("1800", ["model"])  # 30 minutes in seconds

    by_model = []
    totals = {"tokens": 0, "cost": 0, "events": 0}

    # Results are in data['results'][n]['data']
    data_results = results.get("data", {}).get("results", [])
    for item in data_results:
        row = item.get("data", {})
        model = row.get("model", "")
        tokens = row.get("SUM(claude_code.token.usage)", 0) or 0
        cost = row.get("SUM(claude_code.cost.usage)", 0) or 0
        events = row.get("COUNT", 0) or 0

        if model:
            by_model.append({
                "model": friendly_model_name(model),
                "tokens": tokens,
                "cost": cost,
                "events": events
            })

        totals["tokens"] += tokens
        totals["cost"] += cost
        totals["events"] += events

    by_model.sort(key=lambda x: x["tokens"], reverse=True)

    return {"by_model": by_model, "totals": totals}


def fetch_daily_usage() -> list:
    """Fetch daily usage for last 7 days."""
    by_day = []
    base_url = "https://api.honeycomb.io/1"
    env_param = f"environment={HONEYCOMB_ENVIRONMENT}"

    for i in range(7):
        date = datetime.now() - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")

        query_spec = {
            "calculations": [
                {"op": "SUM", "column": "claude_code.token.usage"},
                {"op": "SUM", "column": "claude_code.cost.usage"},
                {"op": "COUNT"}
            ],
            "filters": [
                {"column": "user.email", "op": "=", "value": USER_EMAIL}
            ],
            "start_time": int(date.replace(hour=0, minute=0, second=0).timestamp()),
            "end_time": int((date + timedelta(days=1)).replace(hour=0, minute=0, second=0).timestamp()),
        }

        try:
            # Step 1: Create query
            create_url = f"{base_url}/queries/{HONEYCOMB_DATASET}?{env_param}"
            result = _curl_json(create_url, "POST", query_spec)
            query_id = result.get("id")
            if not query_id:
                print(f"Daily {date_str}: no query_id: {result}")
                by_day.append({"date": date_str, "tokens": 0, "cost": 0, "events": 0})
                continue

            # Step 2: Execute query
            exec_url = f"{base_url}/query_results/{HONEYCOMB_DATASET}?{env_param}"
            exec_result = _curl_json(exec_url, "POST", {"query_id": query_id})
            result_id = exec_result.get("id")
            if not result_id:
                print(f"Daily {date_str}: no result_id: {exec_result}")
                by_day.append({"date": date_str, "tokens": 0, "cost": 0, "events": 0})
                continue

            # Step 3: Poll for results
            poll_url = f"{base_url}/query_results/{HONEYCOMB_DATASET}/{result_id}?{env_param}"
            for _ in range(10):
                results = _curl_json(poll_url)
                if results.get("complete"):
                    break
                time.sleep(0.3)

            # Parse results from data['results'][0]['data']
            data_results = results.get("data", {}).get("results", [])
            if data_results:
                row = data_results[0].get("data", {})
                by_day.append({
                    "date": date_str,
                    "tokens": row.get("SUM(claude_code.token.usage)", 0) or 0,
                    "cost": row.get("SUM(claude_code.cost.usage)", 0) or 0,
                    "events": row.get("COUNT", 0) or 0
                })
            else:
                by_day.append({"date": date_str, "tokens": 0, "cost": 0, "events": 0})
        except Exception as e:
            print(f"Error fetching day {date_str}: {e}")
            by_day.append({"date": date_str, "tokens": 0, "cost": 0, "events": 0})

    return by_day


def load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {
            "updated_at": "Never",
            "user": "Unknown",
            "period_days": 7,
            "by_model": [],
            "by_day": [],
            "totals": {"tokens": 0, "cost": 0, "events": 0}
        }
    with open(CACHE_FILE) as f:
        return json.load(f)


class TokenOverlay:
    def __init__(self, mini_mode=False):
        self.mini_mode = mini_mode
        self.current_view = "overall"  # "overall", "daily", or "30min"
        self.auto_refresh_enabled = False
        self.auto_refresh_interval = REFRESH_INTERVAL * 60 * 1000  # Convert minutes to ms
        self.auto_refresh_job = None
        self.last_30min_data = None
        self.settings_open = False
        self.update_available = None  # Set to remote version string if update found
        self.root = tk.Tk()
        self.setup_window()
        self.create_widgets()
        self.update_display()
        # Fetch data on startup if cache is empty or stale
        self.root.after(500, lambda: self.on_refresh(force=False))
        # Auto-check for updates after 2 seconds
        self.root.after(2000, self._auto_check_update)

    def setup_window(self):
        self.root.title("Claude Tokens")
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(False)  # Keep title bar for dragging

        # Position in top-right corner
        screen_width = self.root.winfo_screenwidth()
        if self.mini_mode:
            self.root.geometry(f"180x80+{screen_width - 200}+40")
        else:
            self.root.geometry(f"400x500+{screen_width - 420}+40")

        # Dark theme
        self.root.configure(bg="#1a1a1a")

        # Add settings button
        self.root.bind("<Button-3>", self.on_right_click)  # Right-click menu

    def create_widgets(self):
        # Color scheme - MAXIMUM CONTRAST
        bg_color = "#0d0d0d"         # Almost black background
        fg_color = "#ffffff"          # Pure white text
        accent_color = "#00ff88"      # Neon green
        accent_hover = "#00ff99"
        tab_active_bg = "#00ff88"     # Neon green active
        tab_inactive_bg = "#222222"   # Dark gray
        tab_inactive_fg = "#888888"   # Medium gray
        btn_bg = "#00ff88"            # Neon green buttons
        btn_hover = "#00ff99"         # Lighter green on hover
        btn_fg = "#000000"            # Pure black text on buttons

        # Store colors for later use
        self.colors = {
            "bg": bg_color,
            "fg": fg_color,
            "accent": accent_color,
            "tab_active_bg": tab_active_bg,
            "tab_active_fg": btn_fg,
            "tab_inactive_bg": tab_inactive_bg,
            "tab_inactive_fg": tab_inactive_fg,
        }

        self.root.configure(bg=bg_color)

        if self.mini_mode:
            # Compact display
            self.summary_label = tk.Label(
                self.root,
                text="Loading...",
                font=("SF Mono", 14, "bold"),
                bg=bg_color,
                fg="#00ff88"
            )
            self.summary_label.pack(pady=10)

            self.refresh_btn = tk.Button(
                self.root,
                text="↻",
                font=("SF Mono", 16, "bold"),
                command=lambda: self.on_refresh(force=True),
                bg=btn_bg,
                fg=btn_fg,
                activebackground=btn_hover,
                activeforeground=btn_fg,
                relief="solid",
                borderwidth=2,
                padx=14,
                pady=6,
                cursor="hand2",
                highlightthickness=0
            )
            self.refresh_btn.pack(pady=5)
        else:
            # Full display - Header
            title_frame = tk.Frame(self.root, bg=bg_color)
            title_frame.pack(fill="x", padx=12, pady=(12, 8))

            tk.Label(
                title_frame,
                text="Claude Code Usage",
                font=("SF Mono", 13, "bold"),
                bg=bg_color,
                fg=fg_color
            ).pack(side="left")

            self.updated_label = tk.Label(
                title_frame,
                text="",
                font=("SF Mono", 9),
                bg=bg_color,
                fg="#666666"
            )
            self.updated_label.pack(side="right")

            # Tab buttons with pill style
            self.tab_frame = tk.Frame(self.root, bg=bg_color)
            self.tab_frame.pack(fill="x", padx=12, pady=(0, 10))

            tab_style = {
                "font": ("SF Mono", 10, "bold"),
                "relief": "solid",
                "borderwidth": 2,
                "padx": 16,
                "pady": 8,
                "cursor": "hand2",
                "highlightthickness": 0,
            }

            self.overall_tab = tk.Button(
                self.tab_frame,
                text="Overall",
                command=lambda: self.switch_view("overall"),
                bg=tab_active_bg,
                fg=btn_fg,
                activebackground=btn_hover,
                activeforeground=btn_fg,
                **tab_style
            )
            self.overall_tab.pack(side="left", padx=(0, 6))

            self.daily_tab = tk.Button(
                self.tab_frame,
                text="Daily",
                command=lambda: self.switch_view("daily"),
                bg=tab_inactive_bg,
                fg=tab_inactive_fg,
                activebackground=tab_active_bg,
                activeforeground=btn_fg,
                **tab_style
            )
            self.daily_tab.pack(side="left", padx=(0, 6))

            self.min30_tab = tk.Button(
                self.tab_frame,
                text="30min",
                command=lambda: self.switch_view("30min"),
                bg=tab_inactive_bg,
                fg=tab_inactive_fg,
                activebackground=tab_active_bg,
                activeforeground=btn_fg,
                **tab_style
            )
            self.min30_tab.pack(side="left")

            # Content frame
            self.content_frame = tk.Frame(self.root, bg=bg_color)
            self.content_frame.pack(fill="both", expand=True, padx=12)

            # Overall view frame
            self.overall_frame = tk.Frame(self.content_frame, bg=bg_color)

            # Summary with large numbers
            self.summary_frame = tk.Frame(self.overall_frame, bg=bg_color)
            self.summary_frame.pack(fill="x", pady=(5, 10))

            self.tokens_label = tk.Label(
                self.summary_frame,
                text="0",
                font=("SF Mono", 28, "bold"),
                bg=bg_color,
                fg="#00ff88"
            )
            self.tokens_label.pack(side="left")

            tk.Label(
                self.summary_frame,
                text=" tokens",
                font=("SF Mono", 12),
                bg=bg_color,
                fg="#666666"
            ).pack(side="left", anchor="s", pady=8)

            self.cost_label = tk.Label(
                self.summary_frame,
                text="$0",
                font=("SF Mono", 20, "bold"),
                bg=bg_color,
                fg="#f5a623"  # Orange/gold
            )
            self.cost_label.pack(side="right")

            # Model breakdown
            self.models_frame = tk.Frame(self.overall_frame, bg=bg_color)
            self.models_frame.pack(fill="both", expand=True)

            self.model_labels = []

            # Daily view frame
            self.daily_frame = tk.Frame(self.content_frame, bg=bg_color)
            self.daily_labels = []

            # 30min view frame
            self.min30_frame = tk.Frame(self.content_frame, bg=bg_color)
            self.min30_labels = []

            # Show overall view by default
            self.overall_frame.pack(fill="both", expand=True)

            # Separator
            sep = tk.Frame(self.root, bg="#333333", height=1)
            sep.pack(fill="x", padx=12, pady=(10, 8))

            # Bottom controls
            btn_frame = tk.Frame(self.root, bg=bg_color)
            btn_frame.pack(fill="x", padx=12, pady=(0, 5))

            self.refresh_btn = tk.Button(
                btn_frame,
                text="↻ Refresh",
                font=("SF Mono", 11, "bold"),
                command=lambda: self.on_refresh(force=True),
                bg=btn_bg,
                fg=btn_fg,
                activebackground=btn_hover,
                activeforeground=btn_fg,
                relief="solid",
                borderwidth=2,
                padx=18,
                pady=10,
                cursor="hand2",
                highlightthickness=0
            )
            self.refresh_btn.pack(side="left")

            self.update_btn = tk.Button(
                btn_frame,
                text="Update",
                font=("SF Mono", 11, "bold"),
                command=self.check_and_apply_update,
                bg="#4488ff",
                fg=btn_fg,
                activebackground="#5599ff",
                activeforeground=btn_fg,
                relief="solid",
                borderwidth=2,
                padx=18,
                pady=10,
                cursor="hand2",
                highlightthickness=0
            )
            self.update_btn.pack(side="left", padx=(6, 0))

            self.status_label = tk.Label(
                btn_frame,
                text="",
                font=("SF Mono", 9),
                bg=bg_color,
                fg="#666666"
            )
            self.status_label.pack(side="right", padx=(0, 5))

            # Auto-refresh toggle + Settings button
            toggle_frame = tk.Frame(self.root, bg=bg_color)
            toggle_frame.pack(fill="x", padx=12, pady=(0, 12))

            self.auto_refresh_var = tk.BooleanVar(value=False)
            self.auto_refresh_check = tk.Checkbutton(
                toggle_frame,
                text=f"Auto-refresh ({REFRESH_INTERVAL}min)",
                variable=self.auto_refresh_var,
                command=self.toggle_auto_refresh,
                font=("SF Mono", 9, "bold"),
                bg=bg_color,
                fg="#00ff88",
                activebackground=bg_color,
                activeforeground="#00ff88",
                selectcolor="#1a1a1a",
                highlightthickness=1,
                highlightbackground="#00ff88",
                cursor="hand2"
            )
            self.auto_refresh_check.pack(side="left")

            self.settings_btn = tk.Button(
                toggle_frame,
                text="⚙ Settings",
                font=("SF Mono", 9, "bold"),
                command=self.open_settings,
                bg="#333333",
                fg="#00ff88",
                activebackground="#444444",
                activeforeground="#00ff88",
                relief="solid",
                borderwidth=1,
                padx=12,
                pady=4,
                cursor="hand2",
                highlightthickness=0
            )
            self.settings_btn.pack(side="right", padx=(5, 0))

    def switch_view(self, view):
        if view == self.current_view:
            return
        self.current_view = view

        c = self.colors

        # Reset all tabs to inactive
        for tab in [self.overall_tab, self.daily_tab, self.min30_tab]:
            tab.config(bg=c["tab_inactive_bg"], fg=c["tab_inactive_fg"])

        # Hide all frames
        self.overall_frame.pack_forget()
        self.daily_frame.pack_forget()
        self.min30_frame.pack_forget()

        if view == "overall":
            self.overall_tab.config(bg=c["tab_active_bg"], fg=c["tab_active_fg"])
            self.overall_frame.pack(fill="both", expand=True)
        elif view == "daily":
            self.daily_tab.config(bg=c["tab_active_bg"], fg=c["tab_active_fg"])
            self.daily_frame.pack(fill="both", expand=True)
            self.update_daily_view()
        elif view == "30min":
            self.min30_tab.config(bg=c["tab_active_bg"], fg=c["tab_active_fg"])
            self.min30_frame.pack(fill="both", expand=True)
            self.update_30min_view()

    def update_daily_view(self):
        data = load_cache()

        # Clear old labels
        for label in self.daily_labels:
            label.destroy()
        self.daily_labels = []

        by_day = data.get("by_day", [])
        if not by_day:
            label = tk.Label(
                self.daily_frame,
                text="No daily data - run /tokens",
                font=("SF Mono", 10),
                bg="#1a1a1a",
                fg="#888888"
            )
            label.pack(pady=10)
            self.daily_labels.append(label)
            return

        # Header
        header = tk.Label(
            self.daily_frame,
            text=f"{'Date':<12} {'Tokens':>10} {'Cost':>8}",
            font=("SF Mono", 9, "bold"),
            bg="#1a1a1a",
            fg="#888888"
        )
        header.pack(fill="x", pady=(5, 2))
        self.daily_labels.append(header)

        # Daily rows (up to 7 days)
        for item in by_day[:7]:
            date_str = item.get("date", "Unknown")
            tokens = format_tokens(item.get("tokens", 0))
            cost = format_cost(item.get("cost", 0))

            label = tk.Label(
                self.daily_frame,
                text=f"{date_str:<12} {tokens:>10} {cost:>8}",
                font=("SF Mono", 10),
                bg="#1a1a1a",
                fg="#cccccc"
            )
            label.pack(fill="x")
            self.daily_labels.append(label)

    def update_30min_view(self):
        # Clear old labels
        for label in self.min30_labels:
            label.destroy()
        self.min30_labels = []

        bg_color = "#1e1e1e"

        if not self.last_30min_data:
            label = tk.Label(
                self.min30_frame,
                text="Loading... click Refresh",
                font=("SF Mono", 10),
                bg=bg_color,
                fg="#888888"
            )
            label.pack(pady=10)
            self.min30_labels.append(label)
            return

        # Summary
        totals = self.last_30min_data.get("totals", {})
        summary = tk.Label(
            self.min30_frame,
            text=f"Last 30 min: {format_tokens(totals.get('tokens', 0))} | {format_cost(totals.get('cost', 0))}",
            font=("SF Mono", 12, "bold"),
            bg=bg_color,
            fg="#4ec9b0"
        )
        summary.pack(pady=(5, 10))
        self.min30_labels.append(summary)

        # Model breakdown
        by_model = self.last_30min_data.get("by_model", [])
        if by_model:
            header = tk.Label(
                self.min30_frame,
                text=f"{'Model':<25} {'Tokens':>10}",
                font=("SF Mono", 9, "bold"),
                bg=bg_color,
                fg="#888888"
            )
            header.pack(fill="x", pady=(0, 2))
            self.min30_labels.append(header)

            for item in by_model[:5]:
                model = item.get("model", "Unknown")[:25]
                tokens = format_tokens(item.get("tokens", 0))
                label = tk.Label(
                    self.min30_frame,
                    text=f"{model:<25} {tokens:>10}",
                    font=("SF Mono", 10),
                    bg=bg_color,
                    fg="#cccccc"
                )
                label.pack(fill="x")
                self.min30_labels.append(label)

    def update_display(self):
        data = load_cache()
        totals = data.get("totals", {})

        if self.mini_mode:
            tokens = format_tokens(totals.get("tokens", 0))
            cost = format_cost(totals.get("cost", 0))
            self.summary_label.config(text=f"{tokens} | {cost}")
        else:
            self.tokens_label.config(text=format_tokens(totals.get("tokens", 0)))
            self.cost_label.config(text=format_cost(totals.get("cost", 0)))

            # Update time (convert to Sydney time)
            updated = data.get("updated_at", "Never")
            if updated != "Never":
                try:
                    dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                    sydney_dt = dt.astimezone(SYDNEY_TZ)
                    updated = sydney_dt.strftime("%H:%M")
                except:
                    pass
            self.updated_label.config(text=f"Updated: {updated}")

            # Clear old model labels
            for label in self.model_labels:
                label.destroy()
            self.model_labels = []

            # Add model breakdown
            for item in data.get("by_model", [])[:3]:  # Top 3
                if item.get("tokens", 0) > 0 or item.get("cost", 0) > 0:
                    model_name = item.get("model", "Unknown")
                    # Shorten
                    if len(model_name) > 30:
                        model_name = model_name[:27] + "..."

                    label = tk.Label(
                        self.models_frame,
                        text=f"{model_name}: {format_tokens(item.get('tokens', 0))}",
                        font=("SF Mono", 10),
                        bg="#1a1a1a",
                        fg="#cccccc",
                        anchor="w"
                    )
                    label.pack(fill="x")
                    self.model_labels.append(label)

            # Also update current view if not overall
            if self.current_view == "daily":
                self.update_daily_view()
            elif self.current_view == "30min":
                self.update_30min_view()

        # Schedule next cache check (every 30 seconds)
        self.root.after(30000, self.update_display)

    def on_refresh(self, force=False):
        self.refresh_btn.config(state="disabled", text="Refreshing...")
        if not self.mini_mode:
            self.status_label.config(text="Checking cache...")
        self.root.update()

        def do_refresh():
            try:
                queries_made = 0

                # Check if main cache is fresh (unless forced)
                main_fresh = not force and is_cache_fresh(CACHE_FILE, CACHE_TTL_MAIN)

                if main_fresh:
                    # Use cached data
                    if not self.mini_mode:
                        self.root.after(0, lambda: self.status_label.config(text="Using cache..."))
                else:
                    # Fetch fresh data
                    if not self.mini_mode:
                        self.root.after(0, lambda: self.status_label.config(text="Querying Honeycomb..."))

                    usage_data = fetch_usage_from_honeycomb()
                    queries_made += 1

                    # Write cache immediately with overall data so UI updates fast
                    cache_data = {
                        "updated_at": datetime.utcnow().isoformat() + "Z",
                        "user": USER_EMAIL,
                        "period_days": 7,
                        "by_model": usage_data.get("by_model", []),
                        "by_day": [],
                        "totals": usage_data.get("totals", {"tokens": 0, "cost": 0, "events": 0})
                    }
                    with open(CACHE_FILE, "w") as f:
                        json.dump(cache_data, f, indent=2)
                    # Update UI with overall data right away
                    self.root.after(0, self.update_display)

                    # Now fetch daily data (slow - 7 sequential queries)
                    daily_data = fetch_daily_usage()
                    queries_made += 7

                    # Update cache again with daily data included
                    cache_data["by_day"] = daily_data
                    cache_data["updated_at"] = datetime.utcnow().isoformat() + "Z"
                    with open(CACHE_FILE, "w") as f:
                        json.dump(cache_data, f, indent=2)

                # Always refresh 30min data if stale or forced
                cached_30min = load_30min_cache()
                if force or cached_30min is None:
                    self.last_30min_data = fetch_30min_usage()
                    save_30min_cache(self.last_30min_data)
                    queries_made += 1
                else:
                    self.last_30min_data = cached_30min

                self.root.after(0, lambda: self.on_refresh_complete(True, queries_made=queries_made))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.root.after(0, lambda err=str(e): self.on_refresh_complete(False, err))

        # Run in background thread to avoid blocking UI
        threading.Thread(target=do_refresh, daemon=True).start()

    def on_refresh_complete(self, success, error=None, queries_made=0):
        self.refresh_btn.config(state="normal", text="↻" if self.mini_mode else "↻ Refresh")

        if not self.mini_mode:
            if success:
                if queries_made > 0:
                    self.status_label.config(text=f"Updated ({queries_made} queries)", fg="#4ec9b0")
                else:
                    self.status_label.config(text="From cache", fg="#888888")
            else:
                self.status_label.config(text=f"Error: {error[:20]}" if error else "Error", fg="#f44747")

            # Clear status after delay
            self.root.after(5000, lambda: self.status_label.config(text="", fg="#888888"))

        # Update display
        self.update_display()

        # Update 30min view if visible
        if self.current_view == "30min":
            self.update_30min_view()

    def toggle_auto_refresh(self):
        self.auto_refresh_enabled = self.auto_refresh_var.get()
        if self.auto_refresh_enabled:
            self.schedule_auto_refresh()
        elif self.auto_refresh_job:
            self.root.after_cancel(self.auto_refresh_job)
            self.auto_refresh_job = None

    def schedule_auto_refresh(self):
        if self.auto_refresh_enabled:
            self.auto_refresh_job = self.root.after(self.auto_refresh_interval, self.auto_refresh_tick)

    def auto_refresh_tick(self):
        if self.auto_refresh_enabled:
            self.on_refresh(force=False)  # Use cache if fresh
            self.schedule_auto_refresh()

    def on_right_click(self, event):
        """Right-click menu."""
        menu = tk.Menu(self.root, tearoff=0, bg="#222222", fg="#ffffff")
        menu.add_command(label="Settings", command=self.open_settings)
        menu.add_command(label="Uninstall", command=self.uninstall)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def open_settings(self):
        """Open settings in same window by replacing content."""
        if self.settings_open:
            return

        self.settings_open = True

        # Hide tab buttons
        if hasattr(self, 'tab_frame'):
            self.tab_frame.pack_forget()

        # Hide existing content frames
        self.overall_frame.pack_forget()
        self.daily_frame.pack_forget()
        self.min30_frame.pack_forget()

        # Create settings frame
        self.settings_frame = tk.Frame(self.content_frame, bg="#0d0d0d")
        self.settings_frame.pack(fill="both", expand=True, padx=12)

        # Settings title
        title = tk.Label(
            self.settings_frame,
            text="Settings",
            font=("SF Mono", 16, "bold"),
            bg="#0d0d0d",
            fg="#ffffff"
        )
        title.pack(pady=(20, 5), padx=20)

        # Version info
        tk.Label(
            self.settings_frame,
            text=f"v{__version__}",
            font=("SF Mono", 9),
            bg="#0d0d0d",
            fg="#666666"
        ).pack(pady=(0, 15))

        # Color scheme
        bg_color = "#0d0d0d"
        accent_color = "#00ff88"

        settings_window = self.settings_frame

        settings_window.configure(bg=bg_color)

        # Refresh interval
        interval_frame = tk.Frame(settings_window, bg=bg_color)
        interval_frame.pack(fill="x", padx=20, pady=10)

        tk.Label(
            interval_frame,
            text="Auto-refresh interval (1-60 min):",
            font=("SF Mono", 10),
            bg=bg_color,
            fg="#ffffff"
        ).pack(side="left", anchor="w")

        self.interval_var = tk.StringVar(value=str(REFRESH_INTERVAL))
        interval_spinbox = tk.Spinbox(
            interval_frame,
            from_=1,
            to=60,
            textvariable=self.interval_var,
            font=("SF Mono", 10),
            bg="#222222",
            fg=accent_color,
            width=5,
            relief="solid",
            borderwidth=1
        )
        interval_spinbox.pack(side="right")

        # API Key
        apikey_frame = tk.Frame(settings_window, bg=bg_color)
        apikey_frame.pack(fill="x", padx=20, pady=10)

        tk.Label(
            apikey_frame,
            text="Honeycomb API Key:",
            font=("SF Mono", 10),
            bg=bg_color,
            fg="#ffffff"
        ).pack(anchor="w")

        self.apikey_var = tk.StringVar(value=HONEYCOMB_API_KEY[:16] + "***" if HONEYCOMB_API_KEY else "")
        apikey_entry = tk.Entry(
            settings_window,
            textvariable=self.apikey_var,
            font=("SF Mono", 9),
            bg="#222222",
            fg=accent_color,
            relief="solid",
            borderwidth=1,
            width=50
        )
        apikey_entry.pack(fill="x", padx=20, pady=(5, 10))

        # Email
        email_frame = tk.Frame(settings_window, bg=bg_color)
        email_frame.pack(fill="x", padx=20, pady=10)

        tk.Label(
            email_frame,
            text="Email:",
            font=("SF Mono", 10),
            bg=bg_color,
            fg="#ffffff"
        ).pack(anchor="w")

        self.email_var = tk.StringVar(value=USER_EMAIL)
        email_entry = tk.Entry(
            settings_window,
            textvariable=self.email_var,
            font=("SF Mono", 9),
            bg="#222222",
            fg=accent_color,
            relief="solid",
            borderwidth=1,
            width=50
        )
        email_entry.pack(fill="x", padx=20, pady=(5, 10))

        # Separator
        sep = tk.Frame(settings_window, bg="#333333", height=1)
        sep.pack(fill="x", padx=20, pady=15)

        # Buttons
        btn_frame = tk.Frame(settings_window, bg=bg_color)
        btn_frame.pack(fill="x", padx=20, pady=(0, 15))

        back_btn = tk.Button(
            btn_frame,
            text="← Back",
            font=("SF Mono", 10, "bold"),
            command=self.close_settings,
            bg="#333333",
            fg="#000000",
            activebackground="#444444",
            activeforeground="#000000",
            relief="solid",
            borderwidth=2,
            padx=8,
            pady=6,
            cursor="hand2",
            highlightthickness=0
        )
        back_btn.pack(side="left", padx=2)

        save_btn = tk.Button(
            btn_frame,
            text="Save",
            font=("SF Mono", 10, "bold"),
            command=lambda: self.save_settings(settings_window, self.interval_var.get(), self.apikey_var.get(), self.email_var.get()),
            bg=accent_color,
            fg="#000000",
            activebackground="#00ff99",
            activeforeground="#000000",
            relief="solid",
            borderwidth=2,
            padx=10,
            pady=6,
            cursor="hand2",
            highlightthickness=0
        )
        save_btn.pack(side="left", padx=2)

        uninstall_btn = tk.Button(
            btn_frame,
            text="Uninstall",
            font=("SF Mono", 10, "bold"),
            command=lambda: self.uninstall_from_settings(),
            bg="#ff2222",
            fg="#000000",
            activebackground="#ff4444",
            activeforeground="#000000",
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=6,
            cursor="hand2",
            highlightthickness=0
        )
        uninstall_btn.pack(side="right", padx=2)

    def save_settings(self, window, interval, apikey, email):
        """Save settings to config."""
        try:
            interval_int = int(interval)
            if interval_int < 1 or interval_int > 60:
                tk.messagebox.showerror("Invalid", "Interval must be 1-60 minutes")
                return

            if not apikey or not email:
                tk.messagebox.showerror("Invalid", "API key and email required")
                return

            # Update global config
            global CONFIG, HONEYCOMB_API_KEY, USER_EMAIL, REFRESH_INTERVAL
            CONFIG["refresh_interval"] = interval_int
            CONFIG["api_key"] = apikey if len(apikey) > 10 else HONEYCOMB_API_KEY
            CONFIG["user_email"] = email
            HONEYCOMB_API_KEY = CONFIG["api_key"]
            USER_EMAIL = CONFIG["user_email"]
            REFRESH_INTERVAL = interval_int

            save_config(CONFIG)

            # Update interval label
            self.auto_refresh_check.config(text=f"Auto-refresh ({REFRESH_INTERVAL}min)")
            self.auto_refresh_interval = REFRESH_INTERVAL * 60 * 1000

            # Show success message
            tk.messagebox.showinfo("Success", "Settings saved! Please restart the app for changes to take effect.")
            self.close_settings()
        except ValueError:
            tk.messagebox.showerror("Error", "Invalid refresh interval")

    def close_settings(self):
        """Close settings and return to previous view."""
        if hasattr(self, 'settings_frame'):
            self.settings_frame.pack_forget()
            self.settings_frame.destroy()
        self.settings_open = False

        # Show tab buttons again
        if hasattr(self, 'tab_frame'):
            self.tab_frame.pack(fill="x", padx=12, pady=(0, 10))

        # Return to previous view
        if self.current_view == "overall":
            self.overall_frame.pack(fill="both", expand=True)
        elif self.current_view == "daily":
            self.daily_frame.pack(fill="both", expand=True)
        elif self.current_view == "30min":
            self.min30_frame.pack(fill="both", expand=True)

    def uninstall_from_settings(self):
        """Uninstall and close settings."""
        if tk.messagebox.askyesno("Uninstall", "Are you sure? This will remove all configuration."):
            try:
                # Remove config directory
                import shutil
                if CONFIG_DIR.exists():
                    shutil.rmtree(CONFIG_DIR)

                # Remove from launchd if installed
                plist_path = Path.home() / "Library/LaunchAgents/com.token-overlay.plist"
                if plist_path.exists():
                    plist_path.unlink()

                tk.messagebox.showinfo("Uninstalled", "Token overlay has been removed.")
                self.root.quit()
            except Exception as e:
                tk.messagebox.showerror("Error", f"Uninstall failed: {e}")

    def uninstall(self):
        """Uninstall the tool."""
        if tk.messagebox.askyesno("Uninstall", "Are you sure? This will remove all configuration."):
            try:
                # Remove config directory
                import shutil
                if CONFIG_DIR.exists():
                    shutil.rmtree(CONFIG_DIR)

                # Remove from launchd if installed
                plist_path = Path.home() / "Library/LaunchAgents/com.token-overlay.plist"
                if plist_path.exists():
                    plist_path.unlink()

                tk.messagebox.showinfo("Uninstalled", "Token overlay has been removed.")
                self.root.quit()
            except Exception as e:
                tk.messagebox.showerror("Error", f"Uninstall failed: {e}")

    def _auto_check_update(self):
        """Background update check on startup."""
        def do_check():
            remote_ver, _ = check_for_update()
            if remote_ver:
                self.update_available = remote_ver
                self.root.after(0, lambda: self._show_update_indicator())
        threading.Thread(target=do_check, daemon=True).start()

    def _show_update_indicator(self):
        """Show update available indicator on Update button."""
        if hasattr(self, "update_btn"):
            self.update_btn.config(text="⬆ Update", bg="#ff8800", activebackground="#ffaa33")

    def check_and_apply_update(self):
        """Check for updates and apply if available."""
        if not self.mini_mode:
            self.status_label.config(text="Checking for updates...", fg="#4488ff")
        self.root.update()

        def do_check():
            try:
                if self.update_available:
                    rv = self.update_available
                    msg = f"Update available: v{__version__} → v{rv}"
                else:
                    rv, msg = check_for_update()

                if rv is None:
                    self.root.after(0, lambda m=msg: self._show_update_result(m, "failed" in m.lower()))
                else:
                    self.root.after(0, lambda r=rv, m=msg: self._confirm_and_install(r, m))
            except Exception as e:
                self.root.after(0, lambda: self._show_update_result(f"Error: {e}", True))

        threading.Thread(target=do_check, daemon=True).start()

    def _confirm_and_install(self, remote_version, message):
        """Show confirmation dialog and install update."""
        proceed = tk.messagebox.askyesno(
            "Update Available",
            f"{message}\n\nDownload and install now?\nThe app will need to restart after updating."
        )
        if not proceed:
            return

        if not self.mini_mode:
            self.status_label.config(text="Downloading update...", fg="#4488ff")
        self.root.update()

        def do_install():
            result = download_and_install_update()
            success = "successfully" in result.lower()
            self.root.after(0, lambda: self._update_complete(result, success))

        threading.Thread(target=do_install, daemon=True).start()

    def _update_complete(self, message, success):
        """Handle update completion."""
        if success:
            self.update_available = None
            if hasattr(self, "update_btn"):
                self.update_btn.config(text="Update", bg="#4488ff", activebackground="#5599ff")
            restart = tk.messagebox.askyesno(
                "Update Complete",
                f"{message}\n\nRestart now to use the new version?"
            )
            if restart:
                self._restart_app()
            elif not self.mini_mode:
                self.status_label.config(text="Restart required", fg="#4488ff")
        else:
            tk.messagebox.showerror("Update Failed", message)
            if not self.mini_mode:
                self.status_label.config(text="Update failed", fg="#f44747")

    def _show_update_result(self, message, is_error=False):
        """Show update check result."""
        if is_error:
            tk.messagebox.showerror("Update Check", message)
        else:
            tk.messagebox.showinfo("Update Check", message)
        if not self.mini_mode:
            self.status_label.config(
                text=message[:30], fg="#f44747" if is_error else "#4488ff"
            )
            self.root.after(5000, lambda: self.status_label.config(text="", fg="#888888"))

    def _restart_app(self):
        """Restart the application."""
        cleanup_pid_file()
        python = sys.executable
        script = os.path.abspath(sys.argv[0])
        args = sys.argv[1:]
        self.root.destroy()
        os.execv(python, [python, script] + args)

    def run(self):
        self.root.mainloop()


def main():
    check_pid_file()
    import atexit
    atexit.register(cleanup_pid_file)

    mini_mode = "--mini" in sys.argv
    app = TokenOverlay(mini_mode=mini_mode)
    app.run()


if __name__ == "__main__":
    main()
