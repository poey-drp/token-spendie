#!/usr/bin/env python3
"""Token Spendie — macOS Menu Bar Token Monitor for Claude, Codex & Gemini."""

import json
import os
import re
import signal
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import rumps

# ── Paths ───────────────────────────────────────────────────────────────────────
HOME = Path.home()
CLAUDE_PROJECTS_DIR = HOME / ".claude" / "projects"
CODEX_LOG_FILE      = HOME / ".codex" / "log" / "codex-tui.log"
GEMINI_LOGS_FILE    = HOME / ".gemini" / "tmp" / "gemini-cli" / "logs.json"
GEMINI_CHATS_DIR    = HOME / ".gemini" / "tmp" / "gemini-cli" / "chats"
CONFIG_FILE         = HOME / ".config" / "token_spendie" / "config.json"
LAUNCH_AGENT_PLIST  = HOME / "Library" / "LaunchAgents" / "com.tokenspendie.agent.plist"

APP_NAME = "Token Spendie"

# ── Default config ───────────────────────────────────────────────────────────────
# Limits below count FRESH tokens only (cache reads excluded). They were
# calibrated against Claude Code's own /status (session 7%, week 52%) on
# 2026-05-26 — adjust to your plan: read /status, then set limit = used / pct.
DEFAULT_CONFIG = {
    "claude_session_5h_limit":    18_000_000,   # fresh tokens per 5-hour window
    "claude_weekly_all_limit":     7_500_000,   # fresh tokens per week (all models)
    "claude_weekly_sonnet_limit":  4_000_000,   # fresh tokens per week (Sonnet only)
    "codex_weekly_limit":          2_000_000,   # fresh tokens per week
    "gemini_daily_limit":              1_000,   # requests per day
    "refresh_interval_minutes":            1,   # how often to refresh the UI
    # Claude live limits: poll the API for the real unified rate-limit % that
    # /status shows (reads the OAuth token from Keychain; tiny cost per poll).
    "claude_use_api":                   True,
    "claude_api_poll_minutes":             5,   # how often to hit the API
}

# Selectable refresh intervals shown in the submenu (minutes)
REFRESH_CHOICES = [1, 2, 5, 10, 15, 30, 60]

SESSION_WINDOW_HOURS = 5
BAR_WIDTH = 20


# ── Config helpers ────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Formatting helpers ────────────────────────────────────────────────────────────

def pct_bar(pct: float, width: int = BAR_WIDTH) -> str:
    """Unicode block progress bar."""
    pct = max(0.0, min(pct, 100.0))
    filled = round(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def status_dot(pct: float) -> str:
    """Traffic-light indicator based on usage percentage."""
    if pct >= 85:
        return "🔴"
    if pct >= 60:
        return "🟡"
    return "🟢"


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def fmt_cost(usd: float) -> str:
    if usd >= 100:
        return f"${usd:.0f}"
    if usd >= 1:
        return f"${usd:.2f}"
    return f"${usd:.3f}"


def humanize_delta(seconds: float) -> str:
    if seconds <= 0:
        return "now"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def next_utc_midnight() -> datetime:
    now = datetime.now(timezone.utc)
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def next_weekday(weekday: int) -> datetime:
    """Next occurrence of weekday (0=Mon … 6=Sun) at 00:00 UTC."""
    now = datetime.now(timezone.utc)
    days_ahead = (weekday - now.weekday()) % 7 or 7
    return (now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)


# ── Visual styling (AppKit attributed text + PIL gradient bars) ──────────────────────
#
# rumps menus are plain NSMenuItems, so the modern look comes from two tricks:
#   1. setAttributedTitle_ — colored / kerned text instead of emoji dots
#   2. a real gradient PNG set as the item's image instead of ░█ block bars
# Everything is wrapped in try/except so a styling failure degrades to plain text
# rather than crashing the app.

import tempfile

BAR_DIR = Path(tempfile.gettempdir()) / "token_spendie_bars"
BAR_W, BAR_H = 248, 8          # points

# Brand accents (soft, desaturated — elegant, not neon)
BRAND = {
    "claude": (198, 164, 255),
    "codex":  (126, 211, 159),
    "gemini": (122, 170, 255),
}
COST_RGB = (125, 207, 182)   # calm teal-green for $ values


def _grad_rgb(t: float) -> tuple[int, int, int]:
    """Fuel-gauge gradient: green → amber → red across t∈[0,1]."""
    def lerp(a, b, k): return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))
    green, amber, red = (52, 211, 153), (251, 191, 36), (248, 113, 113)
    if t < 0.5:
        return lerp(green, amber, t / 0.5)
    return lerp(amber, red, (t - 0.5) / 0.5)


def bar_icon_path(pct: float) -> str | None:
    """Render (and cache) a rounded gradient progress-bar PNG for `pct`."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    key = int(round(max(0.0, min(pct, 100.0))))
    BAR_DIR.mkdir(parents=True, exist_ok=True)
    path = BAR_DIR / f"bar_{key}.png"
    if path.exists():
        return str(path)

    scale = 3
    W, H = BAR_W * scale, BAR_H * scale
    r = H / 2
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Track
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=r, fill=(255, 255, 255, 30))
    # Fill
    fill_w = int(W * key / 100)
    if fill_w > 0:
        fill_w = max(fill_w, int(H))           # keep a clean rounded cap
        grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        px = grad.load()
        for x in range(W):
            c = _grad_rgb(x / (W - 1))
            for y in range(H):
                px[x, y] = (c[0], c[1], c[2], 255)
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, fill_w - 1, H - 1], radius=r, fill=255)
        img.paste(grad, (0, 0), mask)
    img.save(path)
    return str(path)


def _ns_color(rgb: tuple[int, int, int], alpha: float = 1.0):
    from AppKit import NSColor
    return NSColor.colorWithSRGBRed_green_blue_alpha_(
        rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, alpha)


def _set_attr_title(item, text: str, *, size: float = 13.0, rgb=None,
                    alpha: float = 1.0, bold: bool = False, kern: float = 0.0):
    """Set a single-style attributed title; silently no-op on failure."""
    try:
        from AppKit import (NSAttributedString, NSFont, NSColor,
                            NSFontAttributeName, NSForegroundColorAttributeName,
                            NSKernAttributeName)
        font = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
        color = _ns_color(rgb, alpha) if rgb else NSColor.labelColor().colorWithAlphaComponent_(alpha)
        attrs = {NSFontAttributeName: font, NSForegroundColorAttributeName: color}
        if kern:
            attrs[NSKernAttributeName] = kern
        item._menuitem.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(text, attrs))
    except Exception:
        item.title = text


def _set_metric_title(item, label: str, value: str, status_rgb):
    """`label` in primary text + `value` (status colour) right-aligned to bar edge."""
    try:
        from Foundation import NSMutableAttributedString, NSMakeRange
        from AppKit import (NSFont, NSColor, NSFontAttributeName,
                            NSForegroundColorAttributeName, NSParagraphStyleAttributeName,
                            NSMutableParagraphStyle, NSTextTab)
        # Right tab stop at the bar's right edge → a clean value column.
        para = NSMutableParagraphStyle.alloc().init()
        tab = NSTextTab.alloc().initWithTextAlignment_location_options_(1, BAR_W, {})  # 1=right
        para.setTabStops_([tab])
        full = f"{label}\t{value}"
        m = NSMutableAttributedString.alloc().initWithString_(full)
        whole = NSMakeRange(0, len(full))
        m.addAttribute_value_range_(NSFontAttributeName, NSFont.systemFontOfSize_(13), whole)
        m.addAttribute_value_range_(NSParagraphStyleAttributeName, para, whole)
        m.addAttribute_value_range_(
            NSForegroundColorAttributeName,
            NSColor.labelColor().colorWithAlphaComponent_(0.92),
            NSMakeRange(0, len(label)))
        vstart = len(full) - len(value)
        m.addAttribute_value_range_(
            NSFontAttributeName, NSFont.boldSystemFontOfSize_(13),
            NSMakeRange(vstart, len(value)))
        m.addAttribute_value_range_(
            NSForegroundColorAttributeName, _ns_color(status_rgb),
            NSMakeRange(vstart, len(value)))
        item._menuitem.setAttributedTitle_(m)
    except Exception:
        item.title = f"{label}   {value}"


def _set_bar(item, pct: float):
    """Use a gradient image for the bar row; fall back to a unicode bar."""
    path = bar_icon_path(pct)
    if path:
        try:
            item.title = ""
            item.set_icon(path, dimensions=(BAR_W, BAR_H), template=False)
            return
        except Exception:
            pass
    item.title = f"      {pct_bar(pct)}"


def _set_sf_icon(item, symbol: str, size: float = 14.0):
    """Attach a monochrome SF Symbol (template) to a control item."""
    try:
        from AppKit import NSImage, NSImageSymbolConfiguration
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, None)
        if img is None:
            return
        try:
            cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(size, 5)
            img = img.imageWithSymbolConfiguration_(cfg) or img
        except Exception:
            pass
        img.setTemplate_(True)
        item._menuitem.setImage_(img)
    except Exception:
        pass


def status_rgb(pct: float) -> tuple[int, int, int]:
    if pct >= 85:
        return (248, 113, 113)   # red
    if pct >= 60:
        return (251, 191, 36)    # amber
    return (52, 211, 153)        # green


# ── Claude live limits (official unified rate-limit headers) ─────────────────────────
#
# /status shows server-side limit %, which can't be derived from logs. The same
# numbers come back as `anthropic-ratelimit-unified-*` headers on any API call.
# We read the OAuth token Claude Code already stores in the Keychain and make a
# tiny request to read those headers. We never refresh the token ourselves
# (refresh tokens rotate single-use — doing so would log out the real Claude
# Code); if it's expired we just fall back to the log-based cost view.

import urllib.error
import urllib.request

KEYCHAIN_SERVICE = "Claude Code-credentials"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def _read_claude_token() -> tuple[str | None, int]:
    """Return (access_token, expires_at_ms) from the Keychain, or (None, 0)."""
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=5)
        if out.returncode != 0 or not out.stdout.strip():
            return None, 0
        data = json.loads(out.stdout)
        oauth = data.get("claudeAiOauth", data)
        return oauth.get("accessToken"), int(oauth.get("expiresAt", 0) or 0)
    except Exception:
        return None, 0


def get_claude_unified() -> dict:
    """
    Fetch the live unified rate-limit utilisation that /status shows.
    Returns {ok, s_util, w_util, s_reset, w_reset} or {ok: False, reason}.
    """
    token, expires_ms = _read_claude_token()
    if not token:
        return {"ok": False, "reason": "no token — sign in to Claude Code"}
    if expires_ms and expires_ms / 1000 < datetime.now(timezone.utc).timestamp():
        return {"ok": False, "reason": "token expired — open Claude Code"}

    body = json.dumps({
        "model": "claude-haiku-4-5",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "."}],
    }).encode()
    req = urllib.request.Request(ANTHROPIC_MESSAGES_URL, data=body, headers={
        "authorization": f"Bearer {token}",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "oauth-2025-04-20",
        "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            h = resp.headers

            def _f(key):
                v = h.get(key)
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            def _i(key):
                v = h.get(key)
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return None

            return {
                "ok": True,
                "s_util": _f("anthropic-ratelimit-unified-5h-utilization"),
                "w_util": _f("anthropic-ratelimit-unified-7d-utilization"),
                "s_reset": _i("anthropic-ratelimit-unified-5h-reset"),
                "w_reset": _i("anthropic-ratelimit-unified-7d-reset"),
            }
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"ok": False, "reason": "auth failed — open Claude Code"}
        return {"ok": False, "reason": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:50]}


# ── Claude usage & cost ──────────────────────────────────────────────────────────────
#
# We can't reproduce Claude's server-side limit % from local logs (it weighs
# context size, not raw token count), so instead we report what logs DO measure
# exactly: token volume + an estimated cost. Pricing (USD per 1M tokens) is
# calibrated to reproduce Claude Code's own /usage "Usage by model" figures.

CLAUDE_PRICING = {
    "opus":   {"in": 15.0, "out": 75.0, "cache_write": 18.75, "cache_read": 0.20},
    "sonnet": {"in":  3.0, "out": 15.0, "cache_write":  3.75, "cache_read": 0.30},
    "haiku":  {"in":  1.0, "out":  5.0, "cache_write":  1.25, "cache_read": 0.10},
}


def _model_family(model: str) -> str:
    m = model.lower()
    if "opus" in m:
        return "opus"
    if "haiku" in m:
        return "haiku"
    return "sonnet"


def _msg_cost(usage: dict, model: str) -> float:
    p = CLAUDE_PRICING[_model_family(model)]
    return (
        usage.get("input_tokens", 0)               * p["in"]
        + usage.get("output_tokens", 0)            * p["out"]
        + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]
        + usage.get("cache_read_input_tokens", 0)  * p["cache_read"]
    ) / 1_000_000


class _Bucket:
    __slots__ = ("tokens", "cost")
    def __init__(self):
        self.tokens = 0
        self.cost = 0.0
    def add(self, tok, cost):
        self.tokens += tok
        self.cost += cost


def get_claude_usage() -> dict:
    """
    Returns dict with _Bucket values (tokens + cost) for:
      'session' (5h), 'weekly' (7d), 'weekly_sonnet' (7d), and 'oldest_session' ts.
    Token volume is total throughput (incl. cache); cost uses CLAUDE_PRICING.
    """
    now = datetime.now(timezone.utc)
    session_start = now - timedelta(hours=SESSION_WINDOW_HOURS)
    week_start    = now - timedelta(days=7)

    session, weekly, weekly_sonnet = _Bucket(), _Bucket(), _Bucket()
    oldest_in_session: datetime | None = None

    for jsonl_path in CLAUDE_PROJECTS_DIR.rglob("*.jsonl"):
        try:
            with open(jsonl_path, encoding="utf-8", errors="ignore") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    msg = entry.get("message") or {}
                    usage = msg.get("usage")
                    if not usage:
                        continue
                    ts_str = entry.get("timestamp")
                    if not ts_str:
                        continue
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except ValueError:
                        continue

                    model = msg.get("model") or ""
                    tok = (
                        usage.get("input_tokens", 0)
                        + usage.get("output_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                    )
                    cost = _msg_cost(usage, model)

                    if ts >= session_start:
                        session.add(tok, cost)
                        if oldest_in_session is None or ts < oldest_in_session:
                            oldest_in_session = ts
                    if ts >= week_start:
                        weekly.add(tok, cost)
                        if "sonnet" in model.lower():
                            weekly_sonnet.add(tok, cost)
        except (IOError, PermissionError):
            continue

    return {
        "session": session,
        "weekly": weekly,
        "weekly_sonnet": weekly_sonnet,
        "oldest_session": oldest_in_session,
    }


# ── Codex usage ────────────────────────────────────────────────────────────────────

_CODEX_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z).*?"
    r"model=([\w.\-]+).*?"
    r"codex\.turn\.token_usage\.input_tokens=(\d+) codex\.turn\.token_usage\.input_tokens=\d+.*?"
    r"codex\.turn\.token_usage\.cached_input_tokens=(\d+) .*?"
    r"codex\.turn\.token_usage\.output_tokens=(\d+) codex\.turn\.token_usage\.output_tokens=\d+ .*?"
    r"codex\.turn\.token_usage\.total_tokens=(\d+)"
)


def get_codex_usage() -> tuple[int, int, int]:
    """Returns (session_tokens, weekly_tokens, weekly_turns)."""
    if not CODEX_LOG_FILE.exists():
        return 0, 0, 0

    now = datetime.now(timezone.utc)
    session_start = now - timedelta(hours=SESSION_WINDOW_HOURS)
    week_start    = now - timedelta(days=7)

    session_tokens = weekly_tokens = weekly_turns = 0
    try:
        with open(CODEX_LOG_FILE, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                m = _CODEX_RE.search(line)
                if not m:
                    continue
                ts_str, _model, _inp, cached_str, _out, total_str = m.groups()
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                # Fresh tokens only: total minus cached input (parallels the
                # cache_read exclusion on the Claude side).
                fresh = max(0, int(total_str) - int(cached_str))
                if ts >= session_start:
                    session_tokens += fresh
                if ts >= week_start:
                    weekly_tokens += fresh
                    weekly_turns += 1
    except (IOError, PermissionError):
        pass

    return session_tokens, weekly_tokens, weekly_turns


# ── Gemini usage ───────────────────────────────────────────────────────────────────

def get_gemini_usage() -> int:
    """Count Gemini CLI requests made today (UTC) from local logs."""
    today = datetime.now(timezone.utc).date()
    count = 0

    def is_today(ts_str: str) -> bool:
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).date() == today
        except ValueError:
            return False

    if GEMINI_LOGS_FILE.exists():
        try:
            with open(GEMINI_LOGS_FILE) as fh:
                data = json.load(fh)
            if isinstance(data, list):
                count += sum(1 for e in data if is_today(e.get("timestamp", "")))
        except Exception:
            pass

    if GEMINI_CHATS_DIR.exists():
        seen: set = set()
        for chat_path in GEMINI_CHATS_DIR.rglob("*.json"):
            if chat_path in seen:
                continue
            seen.add(chat_path)
            try:
                with open(chat_path) as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    count += sum(
                        1 for e in data
                        if e.get("type") == "user" and is_today(e.get("timestamp", ""))
                    )
            except Exception:
                continue

    return count


# ── Login-item (LaunchAgent) management ──────────────────────────────────────────

def is_autostart_enabled() -> bool:
    return LAUNCH_AGENT_PLIST.exists()


def _bundle_path() -> str | None:
    """If running from inside a .app bundle, return its absolute path."""
    p = Path(__file__).resolve()
    for parent in p.parents:
        if parent.suffix == ".app":
            return str(parent)
    return None


def _launch_command() -> list[str]:
    """
    Command used to relaunch the app at login.

    Prefer launching the .app via `open` so it runs with full bundle
    privileges (matters when the files live under ~/Documents, which macOS
    TCC restricts for plain launchd-spawned processes).
    """
    bundle = _bundle_path()
    if bundle:
        return ["/usr/bin/open", "-a", bundle]
    return [sys.executable, os.path.abspath(__file__)]


def enable_autostart():
    LAUNCH_AGENT_PLIST.parent.mkdir(parents=True, exist_ok=True)
    args = _launch_command()
    args_xml = "\n".join(f"        <string>{a}</string>" for a in args)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tokenspendie.agent</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>StandardErrorPath</key>
    <string>{HOME}/.config/token_spendie/agent.log</string>
    <key>StandardOutPath</key>
    <string>{HOME}/.config/token_spendie/agent.log</string>
</dict>
</plist>
"""
    LAUNCH_AGENT_PLIST.write_text(plist)
    subprocess.run(["launchctl", "unload", str(LAUNCH_AGENT_PLIST)],
                   capture_output=True)
    subprocess.run(["launchctl", "load", str(LAUNCH_AGENT_PLIST)],
                   capture_output=True)


def disable_autostart():
    if LAUNCH_AGENT_PLIST.exists():
        subprocess.run(["launchctl", "unload", str(LAUNCH_AGENT_PLIST)],
                       capture_output=True)
        LAUNCH_AGENT_PLIST.unlink()


# ── App ────────────────────────────────────────────────────────────────────────────

class TokenSpendieApp(rumps.App):
    def __init__(self):
        # Use a text glyph for the menu-bar item — always visible and crisp,
        # and it adapts to light/dark automatically. (A PNG icon must be sized
        # to the ~22pt bar height or macOS hides it.)
        super().__init__(
            APP_NAME,
            title="◈",
            quit_button=None,
        )
        self.cfg = load_config()
        self._lock = threading.Lock()
        self._last_refresh: datetime | None = None

        # Live Claude limits: cache filled by a background poll thread so the
        # network call never blocks the menu.
        self._claude_api: dict = {"ok": False, "reason": "loading…"}
        self._claude_api_lock = threading.Lock()

        # Menu-bar-only: hide the Dock icon (accessory activation policy).
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().setActivationPolicy_(1)  # Accessory
        except Exception:
            pass

        self._build_menu()
        self._start_timer()
        self._start_claude_poll()
        self._refresh_data()

    # ── Claude live-limits polling (background) ──────────────────────────────────

    def _start_claude_poll(self):
        t = threading.Thread(target=self._claude_poll_loop, daemon=True)
        t.start()

    def _claude_poll_loop(self):
        import time as _time
        while True:
            if self.cfg.get("claude_use_api", True):
                result = get_claude_unified()
                with self._claude_api_lock:
                    if result.get("ok"):
                        self._claude_api = result          # fresh good data
                    else:
                        # keep last good utils if we had them; note the error
                        prev = dict(self._claude_api)
                        prev["ok_now"] = False
                        prev["reason"] = result.get("reason")
                        self._claude_api = prev if prev.get("s_util") is not None else result
                # Push the freshly-polled numbers to the menu right away.
                try:
                    self._refresh_data()
                except Exception:
                    pass
            mins = max(1, self.cfg.get("claude_api_poll_minutes", 5))
            _time.sleep(mins * 60)

    # ── Menu construction ───────────────────────────────────────────────────────

    def _build_menu(self):
        sep = rumps.separator

        self._h_header  = rumps.MenuItem(f"◈  {APP_NAME}", callback=self.on_refresh)
        self._h_updated = rumps.MenuItem("", callback=self.on_refresh)

        # Claude
        self._cl_head   = rumps.MenuItem("CLAUDE")
        self._cl_s_t    = rumps.MenuItem("")
        self._cl_s_b    = rumps.MenuItem("")
        self._cl_s_sub  = rumps.MenuItem("")
        self._cl_w_t    = rumps.MenuItem("")
        self._cl_w_b    = rumps.MenuItem("")
        self._cl_w_sub  = rumps.MenuItem("")
        self._cl_ws_t   = rumps.MenuItem("")
        self._cl_ws_b   = rumps.MenuItem("")
        self._cl_ws_sub = rumps.MenuItem("")

        # Codex
        self._cx_head   = rumps.MenuItem("CODEX")
        self._cx_s_t    = rumps.MenuItem("")
        self._cx_s_b    = rumps.MenuItem("")
        self._cx_w_t    = rumps.MenuItem("")
        self._cx_w_b    = rumps.MenuItem("")
        self._cx_w_sub  = rumps.MenuItem("")

        # Gemini
        self._gm_head   = rumps.MenuItem("GEMINI")
        self._gm_t      = rumps.MenuItem("")
        self._gm_b      = rumps.MenuItem("")
        self._gm_sub    = rumps.MenuItem("")
        self._gm_note   = rumps.MenuItem("   estimate · counted from local logs")

        # Controls — clean labels + native SF Symbols (no emoji)
        self._ctl_refresh = rumps.MenuItem("Refresh now", callback=self.on_refresh)
        self._ctl_interval = rumps.MenuItem("Refresh every")
        self._build_interval_submenu()
        self._ctl_autostart = rumps.MenuItem("Start at login",
                                             callback=self.on_toggle_autostart)
        self._ctl_settings = rumps.MenuItem("Edit limits…", callback=self.on_settings)
        self._ctl_quit = rumps.MenuItem("Quit Token Spendie", callback=self.on_quit)
        _set_sf_icon(self._ctl_refresh,   "arrow.clockwise")
        _set_sf_icon(self._ctl_interval,  "timer")
        _set_sf_icon(self._ctl_autostart, "power")
        _set_sf_icon(self._ctl_settings,  "slider.horizontal.3")
        _set_sf_icon(self._ctl_quit,      "xmark.circle")

        self.menu = [
            self._h_header,
            self._h_updated,
            sep,
            self._cl_head,
            self._cl_s_t, self._cl_s_b, self._cl_s_sub,
            self._cl_w_t, self._cl_w_b, self._cl_w_sub,
            self._cl_ws_t, self._cl_ws_b, self._cl_ws_sub,
            sep,
            self._cx_head,
            self._cx_s_t, self._cx_s_b,
            self._cx_w_t, self._cx_w_b, self._cx_w_sub,
            sep,
            self._gm_head,
            self._gm_t, self._gm_b, self._gm_sub, self._gm_note,
            sep,
            self._ctl_refresh,
            self._ctl_interval,
            self._ctl_autostart,
            self._ctl_settings,
            sep,
            self._ctl_quit,
        ]

        # Header + section labels are non-interactive visual dividers
        for item in (self._cl_head, self._cx_head, self._gm_head):
            item.set_callback(None)

        # Static styling
        _set_attr_title(self._h_header, f"◈   {APP_NAME}", size=14, bold=True, kern=0.3)
        _set_attr_title(self._cl_head, "CLAUDE", size=11, bold=True,
                        rgb=BRAND["claude"], kern=1.6)
        _set_attr_title(self._cx_head, "CODEX", size=11, bold=True,
                        rgb=BRAND["codex"], kern=1.6)
        _set_attr_title(self._gm_head, "GEMINI", size=11, bold=True,
                        rgb=BRAND["gemini"], kern=1.6)

        self._sync_autostart_state()

    def _build_interval_submenu(self):
        self._interval_items = {}
        for mins in REFRESH_CHOICES:
            label = f"{mins} min" if mins < 60 else "1 hour"
            item = rumps.MenuItem(label, callback=self._make_interval_cb(mins))
            self._interval_items[mins] = item
            self._ctl_interval.add(item)
        self._sync_interval_state()

    def _make_interval_cb(self, mins: int):
        def _cb(_sender):
            self.cfg["refresh_interval_minutes"] = mins
            save_config(self.cfg)
            self._sync_interval_state()
            self._start_timer()
            self._refresh_data()
        return _cb

    def _sync_interval_state(self):
        current = self.cfg.get("refresh_interval_minutes", 1)
        for mins, item in self._interval_items.items():
            item.state = 1 if mins == current else 0

    def _sync_autostart_state(self):
        self._ctl_autostart.state = 1 if is_autostart_enabled() else 0

    # ── Timer ────────────────────────────────────────────────────────────────────

    def _start_timer(self):
        if getattr(self, "_timer", None):
            self._timer.stop()
        interval = max(1, self.cfg.get("refresh_interval_minutes", 1)) * 60
        self._timer = rumps.Timer(self._on_timer, interval)
        self._timer.start()

    def _on_timer(self, _sender):
        self._refresh_data()

    # ── Actions ──────────────────────────────────────────────────────────────────

    def on_refresh(self, _=None):
        self._refresh_data()

    def on_toggle_autostart(self, _):
        if is_autostart_enabled():
            disable_autostart()
        else:
            enable_autostart()
        self._sync_autostart_state()

    def on_quit(self, _):
        if getattr(self, "_timer", None):
            self._timer.stop()
        rumps.quit_application()
        # Hard fallback so the background process is always killed.
        os.kill(os.getpid(), signal.SIGTERM)

    def on_settings(self, _):
        cfg = self.cfg
        msg = (
            f"Limits live in:\n{CONFIG_FILE}\n\n"
            f"claude_session_5h_limit:    {cfg['claude_session_5h_limit']:,}\n"
            f"claude_weekly_all_limit:    {cfg['claude_weekly_all_limit']:,}\n"
            f"claude_weekly_sonnet_limit: {cfg['claude_weekly_sonnet_limit']:,}\n"
            f"codex_weekly_limit:         {cfg['codex_weekly_limit']:,}\n"
            f"gemini_daily_limit:         {cfg['gemini_daily_limit']:,}\n\n"
            "Edit the JSON, then click Refresh now (no restart needed)."
        )
        window = rumps.Window(message=msg, title=f"{APP_NAME} — Limits",
                              ok="Open Config", cancel="Close", dimensions=(0, 0))
        if window.run().clicked:
            if not CONFIG_FILE.exists():
                save_config(cfg)
            os.system(f'open "{CONFIG_FILE}"')

    # ── Refresh / render ──────────────────────────────────────────────────────────

    def _refresh_data(self):
        with self._lock:
            self.cfg = load_config()        # pick up edits without restart
            self._sync_interval_state()
            self._render()

    def _render(self):
        cfg = self.cfg
        now = datetime.now(timezone.utc)

        # Claude — prefer live unified rate-limit % (matches /status); else
        # fall back to log-based cost + token volume.
        cl = get_claude_usage()
        cl_sess, cl_week, cl_wsonnet = cl["session"], cl["weekly"], cl["weekly_sonnet"]
        oldest_sess = cl["oldest_session"]
        if oldest_sess:
            reset_at = oldest_sess + timedelta(hours=SESSION_WINDOW_HOURS)
            sess_reset = humanize_delta((reset_at - now).total_seconds())
        else:
            sess_reset = "~5h"
        weekly_reset = next_weekday(1).strftime("Tue, %b %-d")

        with self._claude_api_lock:
            api = dict(self._claude_api)
        use_api = self.cfg.get("claude_use_api", True) and api.get("s_util") is not None

        # Codex
        cx_sess_t, cx_week_t, cx_turns = get_codex_usage()
        cx_w_pct = min(100.0, cx_week_t / cfg["codex_weekly_limit"] * 100)

        # Gemini
        g_count = get_gemini_usage()
        g_pct   = min(100.0, g_count / cfg["gemini_daily_limit"] * 100)
        gem_reset = humanize_delta((next_utc_midnight() - now).total_seconds())

        # Updated label
        self._last_refresh = now
        _set_attr_title(
            self._h_updated,
            f"updated {now.astimezone().strftime('%H:%M:%S')} · click to refresh",
            size=11, alpha=0.45)

        # ── Claude rows ──
        if use_api:
            # Live official limits: Session (5h) + Weekly (7d) as real %.
            s_pct = (api["s_util"] or 0) * 100
            w_pct = (api["w_util"] or 0) * 100
            s_rst = self._fmt_reset_ts(api.get("s_reset"), now, relative=True)
            w_rst = self._fmt_reset_ts(api.get("w_reset"), now, relative=False)
            stale = " · stale" if api.get("ok_now") is False else ""
            self._show_row(self._cl_s_t, self._cl_s_b, self._cl_s_sub, True,
                           "Session", s_pct, f"{int(round(s_pct))}%",
                           f"official · 5h · resets in {s_rst}{stale}")
            self._show_row(self._cl_w_t, self._cl_w_b, self._cl_w_sub, True,
                           "Weekly", w_pct, f"{int(round(w_pct))}%",
                           f"official · all models · resets {w_rst}{stale}")
            # 3rd row: weekly spend estimate from logs as a bonus $ figure
            self._cost_row(self._cl_ws_t, self._cl_ws_b, self._cl_ws_sub,
                           "Spend · 7d", cl_week.cost,
                           f"≈ list-price est · {fmt_tokens(cl_week.tokens)} tokens")
        else:
            # Fallback: cost + token volume from logs.
            hint = ""
            if self.cfg.get("claude_use_api", True):
                hint = f" · {api.get('reason', 'log mode')}"
            self._cost_row(self._cl_s_t, self._cl_s_b, self._cl_s_sub,
                           "Session", cl_sess.cost,
                           f"{fmt_tokens(cl_sess.tokens)} tokens · 5h{hint}")
            self._cost_row(self._cl_w_t, self._cl_w_b, self._cl_w_sub,
                           "Weekly", cl_week.cost,
                           f"{fmt_tokens(cl_week.tokens)} tokens · resets {weekly_reset}")
            self._cost_row(self._cl_ws_t, self._cl_ws_b, self._cl_ws_sub,
                           "Weekly · Sonnet", cl_wsonnet.cost,
                           f"{fmt_tokens(cl_wsonnet.tokens)} · Sonnet only")

        # ── Codex rows ── (session shown as raw volume, no fixed limit)
        cx_s_pct = min(100.0, cx_sess_t / max(cx_week_t, 1) * 100) if cx_week_t else 0.0
        self._row(self._cx_s_t, self._cx_s_b, None,
                  "Session", cx_s_pct, f"{fmt_tokens(cx_sess_t)} tokens", None)
        self._row(self._cx_w_t, self._cx_w_b, self._cx_w_sub,
                  "Weekly", cx_w_pct, f"{int(round(cx_w_pct))}%",
                  f"{fmt_tokens(cx_week_t)} · {cx_turns} turns · resets {weekly_reset}")

        # ── Gemini rows ──
        self._row(self._gm_t, self._gm_b, self._gm_sub,
                  "Daily", g_pct, f"{int(round(g_pct))}%",
                  f"≈{g_count} of {cfg['gemini_daily_limit']} req · resets in {gem_reset}")
        _set_attr_title(self._gm_note, "    estimate · counted from local logs",
                        size=11, alpha=0.4)

    def _row(self, t_item, b_item, sub_item, label, pct, value, sub):
        _set_metric_title(t_item, label, value, status_rgb(pct))
        _set_bar(b_item, pct)
        if sub_item is not None:
            _set_attr_title(sub_item, f"    {sub}", size=11, alpha=0.5)

    def _cost_row(self, t_item, b_item, sub_item, label, cost, sub):
        """Cost headline + token/reset subline; no progress bar (hidden)."""
        _set_metric_title(t_item, label, fmt_cost(cost), COST_RGB)
        try:
            b_item._menuitem.setHidden_(True)
        except Exception:
            b_item.title = ""
        _set_attr_title(sub_item, f"    {sub}", size=11, alpha=0.5)

    def _show_row(self, t_item, b_item, sub_item, with_bar, label, pct, value, sub):
        """Metric row with a gradient bar (un-hides the bar if it was hidden)."""
        try:
            b_item._menuitem.setHidden_(False)
        except Exception:
            pass
        self._row(t_item, b_item, sub_item, label, pct, value, sub)

    @staticmethod
    def _fmt_reset_ts(ts, now, relative: bool) -> str:
        """Format a unix reset timestamp either as a countdown or a date."""
        if not ts:
            return "—"
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        if relative:
            return humanize_delta((dt - now).total_seconds())
        # Include time-of-day so it visibly matches Claude's "Resets Tue 8:00 PM".
        return dt.astimezone().strftime("%a %b %-d, %-I%p")


# ── Entry point ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    TokenSpendieApp().run()
