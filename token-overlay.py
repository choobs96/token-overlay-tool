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
- Dark/Light theme toggle
- Transparency control
"""

__version__ = "1.2.0"

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

# --- Design system ---
PAD = 16
PAD_SM = 8
PAD_XS = 4
FONT_UI = "SF Pro Display"
FONT_MONO = "SF Mono"
BTN_H = 34
BTN_RADIUS = 10

THEMES = {
    "dark": {
        "bg":              "#18181b",
        "bg_card":         "#27272a",
        "bg_input":        "#3f3f46",
        "fg":              "#fafafa",
        "fg_secondary":    "#a1a1aa",
        "fg_muted":        "#71717a",
        "accent":          "#22c55e",
        "accent_hover":    "#16a34a",
        "cost":            "#f59e0b",
        "info":            "#06b6d4",
        "link":            "#3b82f6",
        "link_hover":      "#2563eb",
        "error":           "#ef4444",
        "error_hover":     "#dc2626",
        "warning":         "#f97316",
        "tab_active_bg":   "#22c55e",
        "tab_active_fg":   "#052e16",
        "tab_inactive_bg": "#3f3f46",
        "tab_inactive_fg": "#a1a1aa",
        "btn_primary_bg":  "#22c55e",
        "btn_primary_hover":"#16a34a",
        "btn_primary_fg":  "#052e16",
        "btn_secondary_bg":"#3f3f46",
        "btn_secondary_hover":"#52525b",
        "btn_secondary_fg":"#fafafa",
        "btn_danger_bg":   "#ef4444",
        "btn_danger_hover":"#dc2626",
        "btn_danger_fg":   "#ffffff",
        "btn_link_bg":     "#3b82f6",
        "btn_link_hover":  "#2563eb",
        "btn_link_fg":     "#ffffff",
        "separator":       "#3f3f46",
        "select_color":    "#27272a",
        "tooltip_bg":      "#fafafa",
        "tooltip_fg":      "#18181b",
    },
    "light": {
        "bg":              "#fafafa",
        "bg_card":         "#f0f0f0",
        "bg_input":        "#e4e4e7",
        "fg":              "#18181b",
        "fg_secondary":    "#3f3f46",
        "fg_muted":        "#71717a",
        "accent":          "#16a34a",
        "accent_hover":    "#15803d",
        "cost":            "#b45309",
        "info":            "#0e7490",
        "link":            "#2563eb",
        "link_hover":      "#1d4ed8",
        "error":           "#dc2626",
        "error_hover":     "#b91c1c",
        "warning":         "#ea580c",
        "tab_active_bg":   "#16a34a",
        "tab_active_fg":   "#ffffff",
        "tab_inactive_bg": "#d4d4d8",
        "tab_inactive_fg": "#3f3f46",
        "btn_primary_bg":  "#16a34a",
        "btn_primary_hover":"#15803d",
        "btn_primary_fg":  "#ffffff",
        "btn_secondary_bg":"#d4d4d8",
        "btn_secondary_hover":"#a1a1aa",
        "btn_secondary_fg":"#18181b",
        "btn_danger_bg":   "#dc2626",
        "btn_danger_hover":"#b91c1c",
        "btn_danger_fg":   "#ffffff",
        "btn_link_bg":     "#2563eb",
        "btn_link_hover":  "#1d4ed8",
        "btn_link_fg":     "#ffffff",
        "separator":       "#d4d4d8",
        "select_color":    "#f0f0f0",
        "tooltip_bg":      "#27272a",
        "tooltip_fg":      "#fafafa",
    },
}


def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                config = json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
    config["api_key"] = os.getenv("HONEYCOMB_API_KEY", config.get("api_key", ""))
    config["user_email"] = os.getenv("USER_EMAIL", config.get("user_email", ""))
    config["dataset"] = config.get("dataset", "")
    config["environment"] = config.get("environment", "")
    config["refresh_interval"] = config.get("refresh_interval", 30)
    config.setdefault("theme", "dark")
    config.setdefault("opacity", 1.0)
    if not config.get("api_key") or not config.get("user_email"):
        print("ERROR: Missing config. Run install.sh or set environment variables.")
        sys.exit(1)
    return config


def save_config(config: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def check_pid_file():
    if PID_FILE.exists():
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            try:
                os.kill(old_pid, 0)
                sys.exit(0)
            except ProcessLookupError:
                PID_FILE.unlink()
        except (ValueError, FileNotFoundError):
            pass
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def cleanup_pid_file():
    try:
        PID_FILE.unlink()
    except OSError:
        pass


CONFIG = load_config()
HONEYCOMB_API_KEY = CONFIG["api_key"]
HONEYCOMB_DATASET = CONFIG["dataset"]
HONEYCOMB_ENVIRONMENT = CONFIG["environment"]
USER_EMAIL = CONFIG["user_email"]
REFRESH_INTERVAL = CONFIG["refresh_interval"]

CACHE_TTL_MAIN = 300
CACHE_TTL_30MIN = 60
SYDNEY_TZ = ZoneInfo('Australia/Sydney')

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
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return False


def load_30min_cache() -> dict:
    if not is_cache_fresh(CACHE_30MIN_FILE, CACHE_TTL_30MIN):
        return None
    try:
        with open(CACHE_30MIN_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_30min_cache(data: dict):
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(CACHE_30MIN_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _curl_json(url: str, method: str = "GET", data: dict = None) -> dict:
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
    cmd = ["curl", "-sfL", "--max-time", str(timeout), url]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def _parse_version(version_str: str) -> tuple:
    try:
        return tuple(int(x) for x in version_str.strip().split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def check_for_update() -> tuple:
    try:
        remote_version = _curl_text(VERSION_URL).strip()
        local = _parse_version(__version__)
        remote = _parse_version(remote_version)
        if remote > local:
            return remote_version, f"Update available: v{__version__} \u2192 v{remote_version}"
        else:
            return None, f"Already up to date (v{__version__})"
    except Exception as e:
        return None, f"Update check failed: {e}"


def download_and_install_update() -> str:
    try:
        new_script = _curl_text(SCRIPT_URL, timeout=60)
        if "class TokenOverlay" not in new_script or "__version__" not in new_script:
            return "Error: Downloaded file doesn't look like token-overlay"
        if len(new_script) < 1000:
            return "Error: Downloaded file is suspiciously small"
        install_path = Path(os.path.abspath(sys.argv[0]))
        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(dir=install_path.parent, prefix=".token-overlay-update-")
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
    base_url = "https://api.honeycomb.io/1"
    env_param = f"environment={HONEYCOMB_ENVIRONMENT}"
    query_spec = {
        "calculations": [
            {"op": "SUM", "column": "claude_code.token.usage"},
            {"op": "SUM", "column": "claude_code.cost.usage"},
            {"op": "COUNT"}
        ],
        "filters": [{"column": "user.email", "op": "=", "value": USER_EMAIL}],
        "time_range": int(time_range) if time_range.isdigit() else 604800,
    }
    if breakdowns:
        query_spec["breakdowns"] = breakdowns
        query_spec["limit"] = 20
    try:
        create_url = f"{base_url}/queries/{HONEYCOMB_DATASET}?{env_param}"
        result = _curl_json(create_url, "POST", query_spec)
        query_id = result.get("id")
        if not query_id:
            return {}
        exec_url = f"{base_url}/query_results/{HONEYCOMB_DATASET}?{env_param}"
        exec_result = _curl_json(exec_url, "POST", {"query_id": query_id})
        result_id = exec_result.get("id")
        if not result_id:
            return {}
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
    results = query_honeycomb("604800", ["model"])
    by_model, totals = [], {"tokens": 0, "cost": 0, "events": 0}
    for item in results.get("data", {}).get("results", []):
        row = item.get("data", {})
        model = row.get("model", "")
        tokens = row.get("SUM(claude_code.token.usage)", 0) or 0
        cost = row.get("SUM(claude_code.cost.usage)", 0) or 0
        events = row.get("COUNT", 0) or 0
        if model:
            by_model.append({"model": friendly_model_name(model), "tokens": tokens, "cost": cost, "events": events})
        totals["tokens"] += tokens
        totals["cost"] += cost
        totals["events"] += events
    by_model.sort(key=lambda x: x["tokens"], reverse=True)
    return {"by_model": by_model, "totals": totals}


def fetch_30min_usage() -> dict:
    results = query_honeycomb("1800", ["model"])
    by_model, totals = [], {"tokens": 0, "cost": 0, "events": 0}
    for item in results.get("data", {}).get("results", []):
        row = item.get("data", {})
        model = row.get("model", "")
        tokens = row.get("SUM(claude_code.token.usage)", 0) or 0
        cost = row.get("SUM(claude_code.cost.usage)", 0) or 0
        events = row.get("COUNT", 0) or 0
        if model:
            by_model.append({"model": friendly_model_name(model), "tokens": tokens, "cost": cost, "events": events})
        totals["tokens"] += tokens
        totals["cost"] += cost
        totals["events"] += events
    by_model.sort(key=lambda x: x["tokens"], reverse=True)
    return {"by_model": by_model, "totals": totals}


def fetch_daily_usage() -> list:
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
            "filters": [{"column": "user.email", "op": "=", "value": USER_EMAIL}],
            "start_time": int(date.replace(hour=0, minute=0, second=0).timestamp()),
            "end_time": int((date + timedelta(days=1)).replace(hour=0, minute=0, second=0).timestamp()),
        }
        try:
            create_url = f"{base_url}/queries/{HONEYCOMB_DATASET}?{env_param}"
            result = _curl_json(create_url, "POST", query_spec)
            query_id = result.get("id")
            if not query_id:
                by_day.append({"date": date_str, "tokens": 0, "cost": 0, "events": 0})
                continue
            exec_url = f"{base_url}/query_results/{HONEYCOMB_DATASET}?{env_param}"
            exec_result = _curl_json(exec_url, "POST", {"query_id": query_id})
            result_id = exec_result.get("id")
            if not result_id:
                by_day.append({"date": date_str, "tokens": 0, "cost": 0, "events": 0})
                continue
            poll_url = f"{base_url}/query_results/{HONEYCOMB_DATASET}/{result_id}?{env_param}"
            for _ in range(10):
                results = _curl_json(poll_url)
                if results.get("complete"):
                    break
                time.sleep(0.3)
            data_results = results.get("data", {}).get("results", [])
            if data_results:
                row = data_results[0].get("data", {})
                by_day.append({
                    "date": date_str,
                    "tokens": row.get("SUM(claude_code.token.usage)", 0) or 0,
                    "cost": row.get("SUM(claude_code.cost.usage)", 0) or 0,
                    "events": row.get("COUNT", 0) or 0,
                })
            else:
                by_day.append({"date": date_str, "tokens": 0, "cost": 0, "events": 0})
        except Exception as e:
            print(f"Error fetching day {date_str}: {e}")
            by_day.append({"date": date_str, "tokens": 0, "cost": 0, "events": 0})
    return by_day


def load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {"updated_at": "Never", "user": "Unknown", "period_days": 7,
                "by_model": [], "by_day": [], "totals": {"tokens": 0, "cost": 0, "events": 0}}
    with open(CACHE_FILE) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# UI Components — Canvas-based for pixel-perfect rendering on macOS
# ---------------------------------------------------------------------------

def _draw_floppy(canvas, cx, cy, color):
    """Draw a floppy-disk / save icon centred at (cx, cy)."""
    s = 7
    # Body with folded top-right corner
    canvas.create_polygon(
        cx - s, cy - s,
        cx + s - 3, cy - s,
        cx + s, cy - s + 3,
        cx + s, cy + s,
        cx - s, cy + s,
        fill="", outline=color, width=1.8,
    )
    # Label slot (top centre)
    canvas.create_rectangle(cx - 4, cy - s, cx + 3, cy - 3,
                            fill="", outline=color, width=1.4)
    # Disk window (bottom centre)
    canvas.create_rectangle(cx - 5, cy + 1, cx + 5, cy + s - 1,
                            fill="", outline=color, width=1.4)


def _draw_trash(canvas, cx, cy, color):
    """Draw a trash-can / uninstall icon centred at (cx, cy)."""
    s = 7
    # Lid bar
    canvas.create_line(cx - s, cy - s + 3, cx + s, cy - s + 3,
                       fill=color, width=2)
    # Handle
    canvas.create_line(cx - 2, cy - s + 3, cx - 2, cy - s,
                       fill=color, width=1.5)
    canvas.create_line(cx - 2, cy - s, cx + 2, cy - s,
                       fill=color, width=1.5)
    canvas.create_line(cx + 2, cy - s, cx + 2, cy - s + 3,
                       fill=color, width=1.5)
    # Body (slightly tapered)
    canvas.create_polygon(
        cx - s + 1, cy - s + 5,
        cx + s - 1, cy - s + 5,
        cx + s - 2, cy + s,
        cx - s + 2, cy + s,
        fill="", outline=color, width=1.8,
    )
    # Vertical ribs
    for dx in (-3, 0, 3):
        canvas.create_line(cx + dx, cy - s + 7, cx + dx, cy + s - 2,
                           fill=color, width=1.3)


class RoundedButton(tk.Canvas):
    """Canvas-drawn rounded-corner button (bypasses macOS Aqua theming)."""

    def __init__(self, parent, text="", command=None,
                 bg="#22c55e", fg="#000000", hover_bg=None,
                 font=None, height=BTN_H, radius=BTN_RADIUS,
                 draw_icon=None):
        parent_bg = parent.cget("bg")
        super().__init__(parent, height=height, highlightthickness=0, bd=0, bg=parent_bg)
        self._text = text
        self._command = command
        self._bg = bg
        self._fg = fg
        self._hover_bg = hover_bg or bg
        self._font = font or (FONT_UI, 11, "bold")
        self._radius = radius
        self._disabled = False
        self._draw_icon = draw_icon  # callable(canvas, cx, cy, color)

        self.bind("<Configure>", lambda e: self._draw(self._bg))
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", lambda e: None if self._disabled or not self._command else self._command())
        self.config(cursor="hand2")

    def _on_enter(self, event=None):
        if not self._disabled:
            self._draw(self._hover_bg)

    def _on_leave(self, event=None):
        if not self._disabled:
            self._draw(self._bg)

    def _draw(self, color):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            # Widget not laid out yet — retry shortly
            self.after(30, lambda: self._draw(color))
            return
        r = min(self._radius, h // 2, w // 2)
        pts = [r, 0, w - r, 0, w, 0, w, r,
               w, h - r, w, h, w - r, h,
               r, h, 0, h, 0, h - r, 0, r, 0, 0]
        self.create_polygon(pts, smooth=True, fill=color, outline=color)
        fg = self._fg if not self._disabled else "#71717a"
        if self._draw_icon:
            self._draw_icon(self, w // 2, h // 2, fg)
        else:
            self.create_text(w // 2, h // 2, text=self._text, fill=fg, font=self._font)

    def set_state(self, disabled):
        self._disabled = disabled
        self.config(cursor="" if disabled else "hand2")
        self._draw(self._bg)

    def set_text(self, text):
        self._text = text
        self._draw(self._bg)

    def set_colors(self, bg=None, fg=None, hover_bg=None):
        if bg is not None:
            self._bg = bg
        if fg is not None:
            self._fg = fg
        if hover_bg is not None:
            self._hover_bg = hover_bg
        self._draw(self._bg)


class ToolTip:
    """Hover tooltip — inverted contrast, positioned below widget."""

    def __init__(self, widget, text, colors):
        self.widget = widget
        self.text = text
        self.colors = colors
        self.tw = None
        self._after_id = None
        # prevent GC — store reference on the widget itself
        if not hasattr(widget, "_tooltips"):
            widget._tooltips = []
        widget._tooltips.append(self)
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _schedule(self, event=None):
        self._cancel()
        self._after_id = self.widget.after(350, self._show)

    def _show(self):
        if self.tw:
            return
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tw = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        tk.Label(tw, text=self.text, font=(FONT_UI, 10, "bold"),
                 bg=self.colors["tooltip_bg"], fg=self.colors["tooltip_fg"],
                 padx=10, pady=5).pack()

    def _hide(self, event=None):
        self._cancel()
        if self.tw:
            self.tw.destroy()
            self.tw = None

    def _cancel(self):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None


class OpacitySlider(tk.Canvas):
    """Custom canvas slider for opacity (0.3 - 1.0)."""

    def __init__(self, parent, value=1.0, command=None, colors=None):
        self._colors = colors or {}
        parent_bg = parent.cget("bg")
        super().__init__(parent, height=28, highlightthickness=0, bd=0, bg=parent_bg)
        self._value = value
        self._command = command
        self._dragging = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.config(cursor="hand2")

    def _val_to_x(self, val):
        w = self.winfo_width()
        left, right = 14, 50  # right margin for percentage label
        return left + (val - 0.3) / 0.7 * (w - left - right)

    def _x_to_val(self, x):
        w = self.winfo_width()
        left, right = 14, 50
        v = 0.3 + (x - left) / max(1, w - left - right) * 0.7
        return max(0.3, min(1.0, round(v, 2)))

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20:
            return
        c = self._colors
        track_y = h // 2
        left, right = 14, 50
        track_end = w - right
        # Track background
        self.create_line(left, track_y, track_end, track_y,
                         fill=c.get("bg_input", "#444"), width=4, capstyle="round")
        # Filled portion
        knob_x = self._val_to_x(self._value)
        self.create_line(left, track_y, knob_x, track_y,
                         fill=c.get("accent", "#22c55e"), width=4, capstyle="round")
        # Knob
        self.create_oval(knob_x - 8, track_y - 8, knob_x + 8, track_y + 8,
                         fill=c.get("accent", "#22c55e"), outline="")
        # Value label (right of track, no overlap)
        self.create_text(track_end + 12, track_y, text=f"{self._value:.0%}",
                         anchor="w", fill=c.get("fg_secondary", "#aaa"),
                         font=(FONT_MONO, 10, "bold"))

    def _on_click(self, event):
        self._dragging = True
        self._update_from_x(event.x)

    def _on_drag(self, event):
        if self._dragging:
            self._update_from_x(event.x)

    def _on_release(self, event):
        self._dragging = False

    def _update_from_x(self, x):
        self._value = self._x_to_val(x)
        self._draw()
        if self._command:
            self._command(self._value)

    def get(self):
        return self._value


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------

class TokenOverlay:
    def __init__(self, mini_mode=False):
        self.mini_mode = mini_mode
        self.current_view = "overall"
        self.auto_refresh_enabled = False
        self.auto_refresh_interval = REFRESH_INTERVAL * 60 * 1000
        self.auto_refresh_job = None
        self.last_30min_data = None
        self.settings_open = False
        self.update_available = None
        self.root = tk.Tk()

        theme_name = CONFIG.get("theme", "dark")
        if theme_name not in THEMES:
            theme_name = "dark"
        self.current_theme = theme_name
        self.colors = dict(THEMES[self.current_theme])

        self.setup_window()
        self.create_widgets()
        self.update_display()
        self.root.after(500, lambda: self.on_refresh(force=False))
        self.root.after(2000, self._auto_check_update)

    def setup_window(self):
        self.root.title("Claude Tokens")
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(False)
        screen_width = self.root.winfo_screenwidth()
        if self.mini_mode:
            self.root.geometry(f"180x80+{screen_width - 200}+40")
        else:
            self.root.geometry(f"380x480+{screen_width - 400}+40")
        self.root.configure(bg=self.colors["bg"])
        opacity = CONFIG.get("opacity", 1.0)
        self.root.attributes("-alpha", max(0.3, min(1.0, opacity)))
        self.root.bind("<Button-3>", self.on_right_click)

    def create_widgets(self):
        c = self.colors
        self.root.configure(bg=c["bg"])
        if self.mini_mode:
            self._create_mini(c)
        else:
            self._create_full(c)

    def _create_mini(self, c):
        self.summary_label = tk.Label(self.root, text="Loading\u2026",
                                      font=(FONT_MONO, 14, "bold"), bg=c["bg"], fg=c["accent"])
        self.summary_label.pack(pady=10)
        self.refresh_btn = RoundedButton(self.root, "\u21bb", lambda: self.on_refresh(force=True),
                                         bg=c["btn_primary_bg"], fg=c["btn_primary_fg"],
                                         hover_bg=c["btn_primary_hover"], font=(FONT_UI, 14, "bold"))
        self.refresh_btn.pack(pady=5, padx=PAD, fill="x")

    def _create_full(self, c):
        # --- Header ---
        hdr = tk.Frame(self.root, bg=c["bg"])
        hdr.pack(fill="x", padx=PAD, pady=(PAD, PAD_XS))

        tk.Label(hdr, text="Claude Code Usage", font=(FONT_UI, 13, "bold"),
                 bg=c["bg"], fg=c["fg"]).pack(side="left")
        self.updated_label = tk.Label(hdr, text="", font=(FONT_UI, 9),
                                      bg=c["bg"], fg=c["fg_muted"])
        self.updated_label.pack(side="right")

        # --- Tabs (equal-width, rounded) ---
        self.tab_frame = tk.Frame(self.root, bg=c["bg"])
        self.tab_frame.pack(fill="x", padx=PAD, pady=(PAD_XS, PAD_SM))
        for col in range(3):
            self.tab_frame.columnconfigure(col, weight=1)

        self.overall_tab = RoundedButton(
            self.tab_frame, "Overall", lambda: self.switch_view("overall"),
            bg=c["tab_active_bg"], fg=c["tab_active_fg"], hover_bg=c["accent_hover"],
            font=(FONT_UI, 10, "bold"), height=30, radius=8,
        )
        self.overall_tab.grid(row=0, column=0, sticky="ew", padx=(0, 2))

        self.daily_tab = RoundedButton(
            self.tab_frame, "Daily", lambda: self.switch_view("daily"),
            bg=c["tab_inactive_bg"], fg=c["tab_inactive_fg"], hover_bg=c["btn_secondary_hover"],
            font=(FONT_UI, 10, "bold"), height=30, radius=8,
        )
        self.daily_tab.grid(row=0, column=1, sticky="ew", padx=2)

        self.min30_tab = RoundedButton(
            self.tab_frame, "30 min", lambda: self.switch_view("30min"),
            bg=c["tab_inactive_bg"], fg=c["tab_inactive_fg"], hover_bg=c["btn_secondary_hover"],
            font=(FONT_UI, 10, "bold"), height=30, radius=8,
        )
        self.min30_tab.grid(row=0, column=2, sticky="ew", padx=(2, 0))

        # --- Content ---
        self.content_frame = tk.Frame(self.root, bg=c["bg"])
        self.content_frame.pack(fill="both", expand=True, padx=PAD)

        # Overall
        self.overall_frame = tk.Frame(self.content_frame, bg=c["bg"])

        card = tk.Frame(self.overall_frame, bg=c["bg_card"])
        card.pack(fill="x", pady=(PAD_XS, PAD_SM))
        self.tokens_label = tk.Label(card, text="0", font=(FONT_MONO, 28, "bold"),
                                     bg=c["bg_card"], fg=c["accent"])
        self.tokens_label.pack(side="left", padx=(PAD, 0), pady=PAD_SM)
        tk.Label(card, text="tokens", font=(FONT_UI, 11), bg=c["bg_card"],
                 fg=c["fg_muted"]).pack(side="left", anchor="s", pady=14)
        self.cost_label = tk.Label(card, text="$0", font=(FONT_MONO, 20, "bold"),
                                   bg=c["bg_card"], fg=c["cost"])
        self.cost_label.pack(side="right", padx=(0, PAD), pady=PAD_SM)

        self.models_frame = tk.Frame(self.overall_frame, bg=c["bg"])
        self.models_frame.pack(fill="both", expand=True)
        self.model_labels = []

        # Daily / 30min
        self.daily_frame = tk.Frame(self.content_frame, bg=c["bg"])
        self.daily_labels = []
        self.min30_frame = tk.Frame(self.content_frame, bg=c["bg"])
        self.min30_labels = []

        self.overall_frame.pack(fill="both", expand=True)

        # --- Separator ---
        tk.Frame(self.root, bg=c["separator"], height=1).pack(fill="x", padx=PAD, pady=PAD_XS)

        # --- Bottom bar: refresh + status ---
        bottom = tk.Frame(self.root, bg=c["bg"])
        bottom.pack(fill="x", padx=PAD, pady=PAD_XS)

        self.refresh_btn = RoundedButton(
            bottom, "\u21bb", lambda: self.on_refresh(force=True),
            bg=c["btn_primary_bg"], fg=c["btn_primary_fg"], hover_bg=c["btn_primary_hover"],
            font=(FONT_UI, 13, "bold"), height=32, radius=8,
        )
        self.refresh_btn.pack(side="left", fill="x", expand=False)
        # Force a width for icon button
        self.refresh_btn.config(width=44)
        ToolTip(self.refresh_btn, "Refresh data", c)

        self.status_label = tk.Label(bottom, text="", font=(FONT_UI, 9),
                                     bg=c["bg"], fg=c["fg_muted"])
        self.status_label.pack(side="left", padx=(PAD_SM, 0))

        # --- Footer: auto-refresh, theme toggle, settings ---
        footer = tk.Frame(self.root, bg=c["bg"])
        footer.pack(fill="x", padx=PAD, pady=(PAD_XS, PAD))

        self.auto_refresh_var = tk.BooleanVar(value=False)
        self.auto_refresh_check = tk.Checkbutton(
            footer, text=f"Auto ({REFRESH_INTERVAL}m)",
            variable=self.auto_refresh_var, command=self.toggle_auto_refresh,
            font=(FONT_UI, 9), bg=c["bg"], fg=c["fg_secondary"],
            activebackground=c["bg"], activeforeground=c["accent"],
            selectcolor=c["select_color"], highlightthickness=0, cursor="hand2",
        )
        self.auto_refresh_check.pack(side="left")

        # Settings gear (right)
        self.settings_btn = RoundedButton(
            footer, "\u2699", self.open_settings,
            bg=c["btn_secondary_bg"], fg=c["btn_secondary_fg"], hover_bg=c["btn_secondary_hover"],
            font=(FONT_UI, 14, "bold"), height=32, radius=8,
        )
        self.settings_btn.pack(side="right")
        self.settings_btn.config(width=44)
        ToolTip(self.settings_btn, "Settings", c)

        # Theme toggle (right, before settings) — half-circle icon
        theme_icon = "\u25d0" if self.current_theme == "dark" else "\u25d1"
        self.theme_btn = RoundedButton(
            footer, theme_icon, self._toggle_theme,
            bg=c["btn_secondary_bg"], fg=c["btn_secondary_fg"], hover_bg=c["btn_secondary_hover"],
            font=(FONT_UI, 14, "bold"), height=32, radius=8,
        )
        self.theme_btn.pack(side="right", padx=(0, 4))
        self.theme_btn.config(width=44)
        ToolTip(self.theme_btn, "Toggle theme", c)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def apply_theme(self, theme_name):
        if theme_name not in THEMES:
            return
        self.current_theme = theme_name
        self.colors = dict(THEMES[theme_name])
        CONFIG["theme"] = theme_name
        save_config(CONFIG)
        self._rebuild_ui()

    def _rebuild_ui(self):
        was_settings = self.settings_open
        self.settings_open = False
        for child in self.root.winfo_children():
            child.destroy()
        self.model_labels, self.daily_labels, self.min30_labels = [], [], []
        self.root.configure(bg=self.colors["bg"])
        self.create_widgets()
        self.update_display()
        if self.update_available:
            self._show_update_indicator()
        if was_settings:
            self.open_settings()

    def _toggle_theme(self):
        self.apply_theme("light" if self.current_theme == "dark" else "dark")

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    def switch_view(self, view):
        if view == self.current_view:
            return
        self.current_view = view
        c = self.colors

        for tab, name in [(self.overall_tab, "overall"), (self.daily_tab, "daily"), (self.min30_tab, "30min")]:
            if name == view:
                tab.set_colors(bg=c["tab_active_bg"], fg=c["tab_active_fg"], hover_bg=c["accent_hover"])
            else:
                tab.set_colors(bg=c["tab_inactive_bg"], fg=c["tab_inactive_fg"], hover_bg=c["btn_secondary_hover"])

        self.overall_frame.pack_forget()
        self.daily_frame.pack_forget()
        self.min30_frame.pack_forget()

        if view == "overall":
            self.overall_frame.pack(fill="both", expand=True)
        elif view == "daily":
            self.daily_frame.pack(fill="both", expand=True)
            self.update_daily_view()
        elif view == "30min":
            self.min30_frame.pack(fill="both", expand=True)
            self.update_30min_view()

    def update_daily_view(self):
        c = self.colors
        for w in self.daily_labels:
            w.destroy()
        self.daily_labels = []

        by_day = load_cache().get("by_day", [])
        if not by_day:
            lbl = tk.Label(self.daily_frame, text="No daily data \u2014 click Refresh",
                           font=(FONT_UI, 10), bg=c["bg"], fg=c["fg_muted"])
            lbl.pack(pady=PAD)
            self.daily_labels.append(lbl)
            return

        card = tk.Frame(self.daily_frame, bg=c["bg_card"])
        card.pack(fill="x", pady=PAD_XS)
        self.daily_labels.append(card)

        hdr = tk.Frame(card, bg=c["bg_card"])
        hdr.pack(fill="x", padx=PAD, pady=(PAD_SM, PAD_XS))
        tk.Label(hdr, text="Date", font=(FONT_UI, 9, "bold"), bg=c["bg_card"], fg=c["fg_muted"], anchor="w").pack(side="left", expand=True, fill="x")
        tk.Label(hdr, text="Tokens", font=(FONT_UI, 9, "bold"), bg=c["bg_card"], fg=c["fg_muted"], width=10, anchor="e").pack(side="left")
        tk.Label(hdr, text="Cost", font=(FONT_UI, 9, "bold"), bg=c["bg_card"], fg=c["fg_muted"], width=8, anchor="e").pack(side="left")

        for item in by_day[:7]:
            row = tk.Frame(card, bg=c["bg_card"])
            row.pack(fill="x", padx=PAD, pady=1)
            tk.Label(row, text=item.get("date", ""), font=(FONT_MONO, 10), bg=c["bg_card"], fg=c["fg_secondary"], anchor="w").pack(side="left", expand=True, fill="x")
            tk.Label(row, text=format_tokens(item.get("tokens", 0)), font=(FONT_MONO, 10), bg=c["bg_card"], fg=c["accent"], width=10, anchor="e").pack(side="left")
            tk.Label(row, text=format_cost(item.get("cost", 0)), font=(FONT_MONO, 10), bg=c["bg_card"], fg=c["cost"], width=8, anchor="e").pack(side="left")

        tk.Frame(card, bg=c["bg_card"], height=PAD_SM).pack(fill="x")

    def update_30min_view(self):
        c = self.colors
        for w in self.min30_labels:
            w.destroy()
        self.min30_labels = []

        if not self.last_30min_data:
            lbl = tk.Label(self.min30_frame, text="Loading\u2026 click Refresh",
                           font=(FONT_UI, 10), bg=c["bg"], fg=c["fg_muted"])
            lbl.pack(pady=PAD)
            self.min30_labels.append(lbl)
            return

        totals = self.last_30min_data.get("totals", {})
        card = tk.Frame(self.min30_frame, bg=c["bg_card"])
        card.pack(fill="x", pady=PAD_XS)
        self.min30_labels.append(card)

        tk.Label(card, font=(FONT_MONO, 12, "bold"), bg=c["bg_card"], fg=c["info"],
                 text=f"Last 30 min:  {format_tokens(totals.get('tokens', 0))}  |  {format_cost(totals.get('cost', 0))}",
                 ).pack(pady=(PAD_SM, PAD_XS), padx=PAD)

        by_model = self.last_30min_data.get("by_model", [])
        if by_model:
            hdr = tk.Frame(card, bg=c["bg_card"])
            hdr.pack(fill="x", padx=PAD, pady=(PAD_XS, 2))
            tk.Label(hdr, text="Model", font=(FONT_UI, 9, "bold"), bg=c["bg_card"], fg=c["fg_muted"], anchor="w").pack(side="left", expand=True, fill="x")
            tk.Label(hdr, text="Tokens", font=(FONT_UI, 9, "bold"), bg=c["bg_card"], fg=c["fg_muted"], width=10, anchor="e").pack(side="left")
            for item in by_model[:5]:
                row = tk.Frame(card, bg=c["bg_card"])
                row.pack(fill="x", padx=PAD, pady=1)
                tk.Label(row, text=item.get("model", "?")[:28], font=(FONT_UI, 10), bg=c["bg_card"], fg=c["fg_secondary"], anchor="w").pack(side="left", expand=True, fill="x")
                tk.Label(row, text=format_tokens(item.get("tokens", 0)), font=(FONT_MONO, 10), bg=c["bg_card"], fg=c["accent"], width=10, anchor="e").pack(side="left")

        tk.Frame(card, bg=c["bg_card"], height=PAD_SM).pack(fill="x")

    def update_display(self):
        data = load_cache()
        totals = data.get("totals", {})
        c = self.colors

        if self.mini_mode:
            self.summary_label.config(text=f"{format_tokens(totals.get('tokens', 0))} | {format_cost(totals.get('cost', 0))}")
        else:
            self.tokens_label.config(text=format_tokens(totals.get("tokens", 0)))
            self.cost_label.config(text=format_cost(totals.get("cost", 0)))

            updated = data.get("updated_at", "Never")
            if updated != "Never":
                try:
                    dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                    updated = dt.astimezone(SYDNEY_TZ).strftime("%H:%M")
                except (ValueError, TypeError):
                    pass
            self.updated_label.config(text=f"Updated {updated}")

            for w in self.model_labels:
                w.destroy()
            self.model_labels = []

            for item in data.get("by_model", [])[:3]:
                if item.get("tokens", 0) > 0 or item.get("cost", 0) > 0:
                    name = item.get("model", "Unknown")
                    if len(name) > 30:
                        name = name[:27] + "\u2026"
                    row = tk.Frame(self.models_frame, bg=c["bg"])
                    row.pack(fill="x", pady=1)
                    tk.Label(row, text=name, font=(FONT_UI, 10), bg=c["bg"], fg=c["fg_secondary"], anchor="w").pack(side="left", expand=True, fill="x")
                    tk.Label(row, text=format_tokens(item.get("tokens", 0)), font=(FONT_MONO, 10), bg=c["bg"], fg=c["accent"], anchor="e").pack(side="right")
                    self.model_labels.append(row)

            if self.current_view == "daily":
                self.update_daily_view()
            elif self.current_view == "30min":
                self.update_30min_view()

        self.root.after(30000, self.update_display)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def on_refresh(self, force=False):
        self.refresh_btn.set_text("\u21bb")  # keep ↻ visible
        self.refresh_btn.set_state(disabled=True)
        self._spin_refresh(0)
        if not self.mini_mode:
            self.status_label.config(text="Checking cache\u2026")
        self.root.update()

        def do_refresh():
            try:
                queries_made = 0
                main_fresh = not force and is_cache_fresh(CACHE_FILE, CACHE_TTL_MAIN)
                if main_fresh:
                    if not self.mini_mode:
                        self.root.after(0, lambda: self.status_label.config(text="Using cache\u2026"))
                else:
                    if not self.mini_mode:
                        self.root.after(0, lambda: self.status_label.config(text="Querying Honeycomb\u2026"))
                    usage_data = fetch_usage_from_honeycomb()
                    queries_made += 1
                    cache_data = {
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "user": USER_EMAIL, "period_days": 7,
                        "by_model": usage_data.get("by_model", []), "by_day": [],
                        "totals": usage_data.get("totals", {"tokens": 0, "cost": 0, "events": 0}),
                    }
                    with open(CACHE_FILE, "w") as f:
                        json.dump(cache_data, f, indent=2)
                    self.root.after(0, self.update_display)
                    daily_data = fetch_daily_usage()
                    queries_made += 7
                    cache_data["by_day"] = daily_data
                    cache_data["updated_at"] = datetime.now(timezone.utc).isoformat()
                    with open(CACHE_FILE, "w") as f:
                        json.dump(cache_data, f, indent=2)
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

        threading.Thread(target=do_refresh, daemon=True).start()

    def _spin_refresh(self, frame):
        """Draw a rotating arc spinner on the refresh button."""
        btn = self.refresh_btn
        if not btn._disabled:
            return  # refresh finished
        btn.delete("all")
        w, h = btn.winfo_width(), btn.winfo_height()
        if w < 2:
            self.root.after(30, lambda: self._spin_refresh(frame))
            return
        # Redraw button background
        r = min(btn._radius, h // 2, w // 2)
        pts = [r, 0, w - r, 0, w, 0, w, r,
               w, h - r, w, h, w - r, h,
               r, h, 0, h, 0, h - r, 0, r, 0, 0]
        btn.create_polygon(pts, smooth=True, fill=btn._bg, outline=btn._bg)
        # Draw spinning arc
        cx, cy = w // 2, h // 2
        sz = 8
        start_angle = (frame * 30) % 360
        arc_color = self.colors["fg"]
        btn.create_arc(cx - sz, cy - sz, cx + sz, cy + sz,
                       start=start_angle, extent=270,
                       style="arc", outline=arc_color, width=2.5)
        self.root.after(50, lambda: self._spin_refresh(frame + 1))

    def on_refresh_complete(self, success, error=None, queries_made=0):
        self.refresh_btn.set_state(disabled=False)
        self.refresh_btn.set_text("\u21bb")
        c = self.colors
        if not self.mini_mode:
            if success:
                if queries_made > 0:
                    self.status_label.config(text=f"Updated ({queries_made} queries)", fg=c["info"])
                else:
                    self.status_label.config(text="From cache", fg=c["fg_muted"])
            else:
                self.status_label.config(text=f"Error: {error[:20]}" if error else "Error", fg=c["error"])
            self.root.after(5000, lambda: self.status_label.config(text="", fg=c["fg_muted"]))
        self.update_display()
        if self.current_view == "30min":
            self.update_30min_view()

    # ------------------------------------------------------------------
    # Auto-refresh
    # ------------------------------------------------------------------

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
            self.on_refresh(force=False)
            self.schedule_auto_refresh()

    # ------------------------------------------------------------------
    # Right-click
    # ------------------------------------------------------------------

    def on_right_click(self, event):
        c = self.colors
        menu = tk.Menu(self.root, tearoff=0, bg=c["bg_card"], fg=c["fg"],
                       activebackground=c["btn_secondary_bg"], activeforeground=c["fg"],
                       relief="flat", borderwidth=0)
        menu.add_command(label="Settings", command=self.open_settings)
        menu.add_command(label="Uninstall", command=self.uninstall)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def uninstall(self):
        if tk.messagebox.askyesno("Uninstall", "Remove all configuration?"):
            try:
                import shutil
                if CONFIG_DIR.exists():
                    shutil.rmtree(CONFIG_DIR)
                plist = Path.home() / "Library/LaunchAgents/com.token-overlay.plist"
                if plist.exists():
                    plist.unlink()
                tk.messagebox.showinfo("Done", "Token overlay removed.")
                self.root.quit()
            except Exception as e:
                tk.messagebox.showerror("Error", f"Uninstall failed: {e}")

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def open_settings(self):
        if self.settings_open:
            return
        self.settings_open = True
        c = self.colors

        self._original_api_key = HONEYCOMB_API_KEY
        masked = HONEYCOMB_API_KEY[:16] + "***" if HONEYCOMB_API_KEY else ""
        self._api_key_masked = masked

        if hasattr(self, "tab_frame"):
            self.tab_frame.pack_forget()
        self.overall_frame.pack_forget()
        self.daily_frame.pack_forget()
        self.min30_frame.pack_forget()

        self.settings_frame = sf = tk.Frame(self.content_frame, bg=c["bg"])
        sf.pack(fill="both", expand=True)

        tk.Label(sf, text="Settings", font=(FONT_UI, 16, "bold"), bg=c["bg"], fg=c["fg"]).pack(pady=(PAD, 2))
        tk.Label(sf, text=f"v{__version__}", font=(FONT_UI, 9), bg=c["bg"], fg=c["fg_muted"]).pack(pady=(0, PAD))

        # Interval
        row_int = tk.Frame(sf, bg=c["bg"])
        row_int.pack(fill="x", padx=PAD, pady=PAD_XS)
        tk.Label(row_int, text="Auto-refresh interval (min)", font=(FONT_UI, 10),
                 bg=c["bg"], fg=c["fg_secondary"]).pack(side="left")
        self.interval_var = tk.StringVar(value=str(REFRESH_INTERVAL))
        tk.Spinbox(row_int, from_=1, to=60, textvariable=self.interval_var,
                   font=(FONT_MONO, 10), bg=c["bg_input"], fg=c["fg"],
                   width=4, relief="flat", borderwidth=0, highlightthickness=0,
                   buttonbackground=c["btn_secondary_bg"]).pack(side="right")

        # API key
        tk.Label(sf, text="Honeycomb API Key", font=(FONT_UI, 10),
                 bg=c["bg"], fg=c["fg_secondary"]).pack(anchor="w", padx=PAD, pady=(PAD_SM, 0))
        self.apikey_var = tk.StringVar(value=masked)
        tk.Entry(sf, textvariable=self.apikey_var, font=(FONT_MONO, 10),
                 bg=c["bg_input"], fg=c["fg"], insertbackground=c["fg"],
                 relief="flat", borderwidth=0, highlightthickness=0,
                 ).pack(fill="x", padx=PAD, pady=PAD_XS, ipady=4)

        # Email
        tk.Label(sf, text="Email", font=(FONT_UI, 10),
                 bg=c["bg"], fg=c["fg_secondary"]).pack(anchor="w", padx=PAD, pady=(PAD_SM, 0))
        self.email_var = tk.StringVar(value=USER_EMAIL)
        tk.Entry(sf, textvariable=self.email_var, font=(FONT_MONO, 10),
                 bg=c["bg_input"], fg=c["fg"], insertbackground=c["fg"],
                 relief="flat", borderwidth=0, highlightthickness=0,
                 ).pack(fill="x", padx=PAD, pady=PAD_XS, ipady=4)

        # Opacity
        tk.Label(sf, text="Opacity", font=(FONT_UI, 10),
                 bg=c["bg"], fg=c["fg_secondary"]).pack(anchor="w", padx=PAD, pady=(PAD_SM, 0))
        self.opacity_slider = OpacitySlider(sf, value=CONFIG.get("opacity", 1.0),
                                            command=self._on_opacity_change, colors=c)
        self.opacity_slider.pack(fill="x", padx=PAD, pady=PAD_XS)

        # Separator
        tk.Frame(sf, bg=c["separator"], height=1).pack(fill="x", padx=PAD, pady=PAD)

        # Buttons row 1: back, save
        r1 = tk.Frame(sf, bg=c["bg"])
        r1.pack(fill="x", padx=PAD, pady=(0, PAD_XS))
        r1.columnconfigure(0, weight=1)
        r1.columnconfigure(1, weight=1)

        b_back = RoundedButton(r1, "\u2190", self.close_settings,
                               bg=c["btn_secondary_bg"], fg=c["btn_secondary_fg"],
                               hover_bg=c["btn_secondary_hover"],
                               font=(FONT_UI, 14, "bold"), height=BTN_H)
        b_back.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ToolTip(b_back, "Back", c)

        b_save = RoundedButton(r1, "",
                               lambda: self.save_settings(sf, self.interval_var.get(),
                                                          self.apikey_var.get(), self.email_var.get()),
                               bg=c["btn_primary_bg"], fg=c["btn_primary_fg"],
                               hover_bg=c["btn_primary_hover"],
                               font=(FONT_UI, 14, "bold"), height=BTN_H,
                               draw_icon=_draw_floppy)
        b_save.grid(row=0, column=1, sticky="ew", padx=(2, 0))
        ToolTip(b_save, "Save settings", c)

        # Buttons row 2: update, uninstall
        r2 = tk.Frame(sf, bg=c["bg"])
        r2.pack(fill="x", padx=PAD, pady=(PAD_XS, PAD))
        r2.columnconfigure(0, weight=1)
        r2.columnconfigure(1, weight=1)

        b_update = RoundedButton(r2, "\u2b07", self.check_and_apply_update,
                                 bg=c["btn_link_bg"], fg=c["btn_link_fg"],
                                 hover_bg=c["btn_link_hover"],
                                 font=(FONT_UI, 14, "bold"), height=BTN_H)
        b_update.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ToolTip(b_update, "Check for updates", c)

        b_remove = RoundedButton(r2, "", self.uninstall,
                                 bg=c["btn_danger_bg"], fg=c["btn_danger_fg"],
                                 hover_bg=c["btn_danger_hover"],
                                 font=(FONT_UI, 14, "bold"), height=BTN_H,
                                 draw_icon=_draw_trash)
        b_remove.grid(row=0, column=1, sticky="ew", padx=(2, 0))
        ToolTip(b_remove, "Uninstall", c)

    def _on_opacity_change(self, value):
        self.root.attributes("-alpha", value)

    def save_settings(self, window, interval, apikey, email):
        try:
            interval_int = int(interval)
            if interval_int < 1 or interval_int > 60:
                tk.messagebox.showerror("Invalid", "Interval must be 1-60 minutes")
                return
            if not apikey or not email:
                tk.messagebox.showerror("Invalid", "API key and email required")
                return
            resolved_key = self._original_api_key if apikey == self._api_key_masked else apikey

            global CONFIG, HONEYCOMB_API_KEY, USER_EMAIL, REFRESH_INTERVAL
            CONFIG["refresh_interval"] = interval_int
            CONFIG["api_key"] = resolved_key
            CONFIG["user_email"] = email
            CONFIG["opacity"] = self.opacity_slider.get()
            HONEYCOMB_API_KEY = CONFIG["api_key"]
            USER_EMAIL = CONFIG["user_email"]
            REFRESH_INTERVAL = interval_int
            save_config(CONFIG)

            self.auto_refresh_check.config(text=f"Auto ({REFRESH_INTERVAL}m)")
            self.auto_refresh_interval = REFRESH_INTERVAL * 60 * 1000
            tk.messagebox.showinfo("Saved", "Settings saved!")
            self.close_settings()
        except ValueError:
            tk.messagebox.showerror("Error", "Invalid refresh interval")

    def close_settings(self):
        if hasattr(self, "settings_frame"):
            self.settings_frame.pack_forget()
            self.settings_frame.destroy()
        self.settings_open = False
        if hasattr(self, "tab_frame"):
            self.tab_frame.pack(fill="x", padx=PAD, pady=(PAD_XS, PAD_SM))
        if self.current_view == "overall":
            self.overall_frame.pack(fill="both", expand=True)
        elif self.current_view == "daily":
            self.daily_frame.pack(fill="both", expand=True)
        elif self.current_view == "30min":
            self.min30_frame.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    def _auto_check_update(self):
        def do_check():
            rv, _ = check_for_update()
            if rv:
                self.update_available = rv
                self.root.after(0, self._show_update_indicator)
        threading.Thread(target=do_check, daemon=True).start()

    def _show_update_indicator(self):
        if hasattr(self, "settings_btn"):
            self.settings_btn.set_colors(fg=self.colors["warning"])

    def check_and_apply_update(self):
        if not self.mini_mode:
            self.status_label.config(text="Checking\u2026", fg=self.colors["link"])
        self.root.update()

        def do_check():
            try:
                if self.update_available:
                    rv, msg = self.update_available, f"v{__version__} \u2192 v{self.update_available}"
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
        if not tk.messagebox.askyesno("Update", f"{message}\n\nInstall and restart?"):
            return
        if not self.mini_mode:
            self.status_label.config(text="Downloading\u2026", fg=self.colors["link"])
        self.root.update()

        def do_install():
            result = download_and_install_update()
            success = "successfully" in result.lower()
            self.root.after(0, lambda: self._update_complete(result, success))
        threading.Thread(target=do_install, daemon=True).start()

    def _update_complete(self, message, success):
        if success:
            self.update_available = None
            if hasattr(self, "settings_btn"):
                self.settings_btn.set_colors(fg=self.colors["btn_secondary_fg"])
            if tk.messagebox.askyesno("Done", f"{message}\n\nRestart now?"):
                self._restart_app()
            elif not self.mini_mode:
                self.status_label.config(text="Restart required", fg=self.colors["link"])
        else:
            tk.messagebox.showerror("Failed", message)
            if not self.mini_mode:
                self.status_label.config(text="Update failed", fg=self.colors["error"])

    def _show_update_result(self, message, is_error=False):
        (tk.messagebox.showerror if is_error else tk.messagebox.showinfo)("Update", message)
        if not self.mini_mode:
            self.status_label.config(text=message[:30], fg=self.colors["error"] if is_error else self.colors["link"])
            self.root.after(5000, lambda: self.status_label.config(text="", fg=self.colors["fg_muted"]))

    def _restart_app(self):
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
    app = TokenOverlay(mini_mode="--mini" in sys.argv)
    app.run()


if __name__ == "__main__":
    main()
