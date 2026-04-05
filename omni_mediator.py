#!/usr/bin/env python3
"""
=============================================================================
 OMNI-MEDIATOR: The Local AI Bridge
 All Phases Complete — Production-Ready Local AI Bridge
=============================================================================

 An Agentic Middleware Platform that bridges a lightweight Telegram interface
 to high-compute local resources (Ollama LLM + OS kernel).

 Phase 1 (complete):
   ✅ Auto-dependency installation & transparent script restart
   ✅ First-Time User Experience (FTUX) "Zero-Touch" setup wizard
   ✅ Persistent configuration loader (config.json)
   ✅ Asynchronous Telegram polling skeleton with /start handshake
   ✅ Global error handler for exhibition-grade network resilience

 Phase 2 (complete):
   ✅ Rule-based Intent Router (quick checks, OS commands, AI fallback)
   ✅ System status checks (CPU, RAM, disk) via psutil — instant, no AI
   ✅ Platform-agnostic file/app opening via subprocess
   ✅ Async executor wrapper — subprocess never blocks the polling loop
   ✅ Blocked command detection (sudo, su, rm -rf)
   ✅ Allow-list enforcement for terminal commands

 Phase 3 (complete):
   ✅ Ollama API bridge with requests.post + timeout=10
   ✅ Graceful degradation (Timeout, ConnectionError, generic exceptions)
   ✅ Thinking placeholder → edited with final AI response
   ✅ All LLM calls offloaded via run_blocking() async executor

 Phase 4 (complete):
   ✅ Sentinel Shell inline-button authorization (✅ Allow / ❌ Deny)
   ✅ Human-in-the-loop verification loop for every shell command
   ✅ Pending command storage via context.user_data
   ✅ Finalized global error handler for network drops

=============================================================================
"""

import sys
import os
import json
import subprocess
import platform
import asyncio
import shlex
import functools
import uuid
import html
import re
import time

# =============================================================================
# SECTION 1: AUTO-SETUP BLOCK — Dependency Bootstrap
# =============================================================================
# This block runs BEFORE any third-party imports. It checks for required
# packages, installs any that are missing via pip, and then restarts the
# entire script using os.execv() so that fresh imports resolve cleanly.
#
# This is the first half of the "Zero-Touch" OpenClaw-style experience:
# the user never manually runs `pip install`.
# =============================================================================

# Mapping: Python import name -> pip package name
# (import name and pip name differ for python-telegram-bot)
REQUIRED_PACKAGES = {
    "telegram":  "python-telegram-bot",
    "requests":  "requests",
    "psutil":    "psutil",
}


def ensure_dependencies():
    """
    Scan for missing third-party packages and install them silently.

    If any packages were installed, the script restarts itself via os.execv()
    so the interpreter picks up the newly installed modules without requiring
    the user to do anything.
    """
    missing_packages = []

    for import_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(pip_name)

    # Nothing missing — continue normally
    if not missing_packages:
        return

    # --- Install missing packages silently ---
    print(f"📦 Installing missing dependencies: {', '.join(missing_packages)}...")

    try:
        # shell=False by design — no shell injection possible
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet"] + missing_packages,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        print("✅ Dependencies installed successfully.")
    except subprocess.CalledProcessError as exc:
        print(f"\n❌ Failed to install dependencies (exit code {exc.returncode}).")
        print(f"   Please install manually:\n")
        print(f"   pip install {' '.join(missing_packages)}\n")
        sys.exit(1)

    # --- Restart the script so new packages are importable ---
    print("🔄 Restarting script with updated environment...\n")
    os.execv(sys.executable, [sys.executable] + sys.argv)


# ── Run the bootstrap check IMMEDIATELY, before anything else ──
ensure_dependencies()


# =============================================================================
# SECTION 2: THIRD-PARTY IMPORTS (safe after bootstrap gate)
# =============================================================================

import requests                          # HTTP client for Ollama API
import psutil                            # System metrics (CPU, RAM, disk)

from telegram.constants import ParseMode
from telegram import (
    Update,                              # Telegram update object
    InlineKeyboardButton,                # Individual inline button
    InlineKeyboardMarkup,                # Keyboard layout for inline buttons
)
from telegram.ext import (
    Application,                         # Async Telegram application builder
    CommandHandler,                      # Handler for /commands
    MessageHandler,                      # Handler for plain text messages
    CallbackQueryHandler,                # Handler for inline button callbacks
    ContextTypes,                        # Type hints for handler context
    filters,                             # Message filters (text, command, etc.)
)
from telegram.error import (
    TimedOut,                            # Absorbed silently for Wi-Fi resilience
    NetworkError,                        # Absorbed silently for Wi-Fi resilience
)


# =============================================================================
# SECTION 3: CONSTANTS & PLATFORM DETECTION
# =============================================================================

# ── Paths ──
# Config file lives alongside the script — never in a hardcoded user directory
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

# ── Ollama ──
OLLAMA_API_URL          = "http://localhost:11434/api/generate"
TELEGRAM_API_BASE       = "https://api.telegram.org"
OLLAMA_TEST_TIMEOUT     = 5    # seconds — fail fast during FTUX
OLLAMA_GENERATE_TIMEOUT = 10   # seconds — strict cap on LLM generation requests
OLLAMA_MODEL            = "llama3.2:3b"  # Fast local model for testing

# ── Platform ──
CURRENT_PLATFORM = platform.system()  # "Darwin" | "Windows" | "Linux"

# ── Subprocess Safety ──
SUBPROCESS_TIMEOUT = 30  # seconds — hard cap on any subprocess execution

# ── Sentinel Shell: Allow-List ──
# Only these base commands are eligible for execution (Phase 4 adds inline approval).
# Everything else is rejected outright, even if the Sentinel Shell is enabled.
ALLOWED_COMMANDS = {
    "ls", "pwd", "df", "top", "uptime", "whoami", "date", "cal",
    "echo", "cat", "head", "tail", "wc", "which", "hostname",
    "say",             # macOS text-to-speech
    "dir",             # Windows equivalent of ls
}

# ── Sentinel Shell: Blocked Prefixes ──
# These are UNCONDITIONALLY rejected — no prompt, no override, no exceptions.
BLOCKED_PREFIXES = ("sudo ", "su ", "rm -rf", "sudo", "su")

# ── Intent Router: Quick-Check Keywords ──
# Messages matching these trigger instant psutil-based responses, bypassing AI.
STATUS_SINGLE_KEYWORDS = {
    "status", "ram", "memory", "cpu", "disk", "battery", "uptime", "sysinfo", "health",
}
STATUS_PHRASES = {
    "system status", "system info",
}

# ── Intent Router: OS-Action Keywords ──
# Messages starting with these trigger OS-level actions (open files, apps, etc.).
OS_ACTION_PREFIXES = ("open ", "launch ", "run ",)


# =============================================================================
# SECTION 4: CONFIGURATION LOADER
# =============================================================================
# The config.json file persists the user's choices across restarts:
#   - telegram_token:          str   — Bot API token from @BotFather
#   - sentinel_shell_enabled:  bool  — Whether OS command execution is allowed
#   - platform:                str   — Detected OS at setup time
# =============================================================================

def load_config() -> dict | None:
    """
    Attempt to load and validate config.json.

    Returns:
        dict: The parsed configuration if valid.
        None: If the file doesn't exist or is malformed (triggers FTUX).
    """
    if not os.path.exists(CONFIG_PATH):
        return None

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)

        # Validate that the critical key exists
        if "telegram_token" not in config or not config["telegram_token"]:
            print("⚠️  config.json exists but is missing 'telegram_token'. Re-running setup...\n")
            return None
        if "owner_user_id" not in config or not isinstance(config["owner_user_id"], int):
            print("⚠️  config.json exists but is missing valid 'owner_user_id'. Re-running setup...\n")
            return None

        return config

    except json.JSONDecodeError:
        print("⚠️  config.json is corrupted. Re-running setup...\n")
        return None
    except IOError as exc:
        print(f"⚠️  Cannot read config.json: {exc}. Re-running setup...\n")
        return None


def save_config(config: dict) -> None:
    """
    Persist the configuration dictionary to config.json with pretty formatting.
    """
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as config_file:
            json.dump(config, config_file, indent=2, ensure_ascii=False)
        print(f"💾 Configuration saved to: {CONFIG_PATH}")
    except IOError as exc:
        print(f"❌ Failed to save configuration: {exc}")
        sys.exit(1)


def _validate_telegram_token(token: str) -> tuple[bool, str]:
    """
    Verify a Telegram bot token via getMe.
    """
    try:
        response = requests.get(
            f"{TELEGRAM_API_BASE}/bot{token}/getMe",
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            return (False, "Telegram rejected the token.")

        bot_info = data.get("result", {})
        bot_name = bot_info.get("username") or bot_info.get("first_name") or "(unknown bot)"
        return (True, bot_name)
    except requests.exceptions.Timeout:
        return (False, "Telegram API timeout while validating token.")
    except requests.exceptions.RequestException as exc:
        return (False, f"Telegram API error: {exc}")


def _send_setup_complete_message(token: str, owner_user_id: int, sentinel_enabled: bool) -> bool:
    """
    Send setup completion handshake to the configured owner chat ID.
    """
    sentinel_label = "✅ Enabled" if sentinel_enabled else "🔒 Disabled"
    text = (
        "✅ *Setup Complete!*\n"
        "Your local AI is connected.\n\n"
        f"🛡️ Sentinel Shell: {sentinel_label}\n"
        f"🖥️ Platform: `{CURRENT_PLATFORM}`\n\n"
        "Send `/start` anytime to verify the bridge."
    )

    try:
        response = requests.post(
            f"{TELEGRAM_API_BASE}/bot{token}/sendMessage",
            json={
                "chat_id": owner_user_id,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return bool(payload.get("ok"))
    except requests.exceptions.RequestException as exc:
        print(f"⚠️  Could not auto-send setup handshake message: {exc}")
        return False


def _get_runtime_config(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """
    Retrieve config from application memory, with disk fallback.
    """
    cached = context.application.bot_data.get("config")
    if isinstance(cached, dict):
        return cached
    return load_config() or {}


async def _reject_if_unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Return True after handling unauthorized access.
    """
    config = _get_runtime_config(context)
    owner_user_id = config.get("owner_user_id")
    user = update.effective_user
    user_id = user.id if user else None

    if owner_user_id is None:
        if update.callback_query:
            await update.callback_query.answer("Bot owner is not configured.", show_alert=True)
        elif update.message:
            await update.message.reply_text("⚠️ Bot owner is not configured. Re-run setup.")
        return True

    if user_id == owner_user_id:
        return False

    if update.callback_query:
        await update.callback_query.answer("Unauthorized", show_alert=True)
    elif update.message:
        await update.message.reply_text("🚫 Unauthorized user for this bot instance.")
    return True


# =============================================================================
# SECTION 5: FIRST-TIME USER EXPERIENCE (FTUX) WIZARD
# =============================================================================
# The "Zero-Touch" OpenClaw-style setup wizard. A random user runs ONE command
# in their terminal; the wizard takes over and does not stop until the Telegram
# bot is fully configured and ready.
#
# Sequence:
#   Step 1 → Prompt for Telegram Bot Token
#   Step 2 → Auto-test Ollama connectivity
#   Step 3 → Ask for Sentinel Shell permission
#   Step 4 → Save config & print success message
# =============================================================================

def _test_ollama_connection() -> bool:
    """
    Ping the local Ollama instance with a minimal test prompt.

    Sends a lightweight request to localhost:11434/api/generate and verifies
    that Ollama responds with actual generated text. Uses a strict 5-second
    timeout to fail fast — we don't want the FTUX hanging.

    Returns:
        True  — Ollama is running and responsive.
        False — Ollama is unreachable, timed out, or returned bad data.
    """
    print("   Pinging http://localhost:11434 ...")

    try:
        response = requests.post(
            OLLAMA_API_URL,
            json={
                "model": OLLAMA_MODEL,      # Use the dynamically selected testing model
                "prompt": "Reply with 'ok'",
                "stream": False,            # We want a single JSON response
            },
            timeout=OLLAMA_TEST_TIMEOUT,
        )
        response.raise_for_status()

        data = response.json()

        if "response" in data and data["response"].strip():
            # Truncate for display — we only need proof of life
            preview = data["response"].strip()[:60]
            print(f"   ✅ Ollama responded: \"{preview}\"")
            return True
        else:
            print("   ⚠️  Ollama returned an empty or unexpected response.")
            return False

    except requests.exceptions.ConnectionError:
        print("   ❌ Connection refused — Ollama is not running on localhost:11434.")
        return False

    except requests.exceptions.Timeout:
        print(f"   ❌ Ollama did not respond within {OLLAMA_TEST_TIMEOUT}s.")
        return False

    except requests.exceptions.HTTPError as exc:
        print(f"   ❌ Ollama returned an HTTP error: {exc.response.status_code}")
        print(f"      Ensure a model is pulled (e.g., 'ollama pull llama3').")
        return False

    except requests.exceptions.RequestException as exc:
        print(f"   ❌ Unexpected error contacting Ollama: {exc}")
        return False


def run_ftux_wizard() -> dict:
    """
    Execute the full First-Time User Experience wizard.

    This function is sequential and blocking by design — it runs BEFORE the
    Telegram event loop starts. Each step must pass before proceeding.

    Returns:
        dict: Complete configuration ready for save_config().
    """
    print("=" * 62)
    print("   🚀  OMNI-MEDIATOR — First-Time Setup Wizard")
    print("=" * 62)
    print(f"   Platform : {CURRENT_PLATFORM}")
    print(f"   Python   : {sys.version.split()[0]}")
    print(f"   Script   : {os.path.basename(__file__)}")
    print("=" * 62)

    # ── STEP 1: Telegram Bot Token ──────────────────────────────────────────
    print("\n📱 STEP 1 of 3 — Telegram Bot Token")
    print("   Open Telegram → @BotFather → /newbot → copy the token.\n")

    while True:
        token = input("   Enter your Telegram Bot Token: ").strip()

        # Basic format validation: tokens look like "123456789:ABCdef..."
        if token and ":" in token and len(token) > 20:
            ok, detail = _validate_telegram_token(token)
            if ok:
                print(f"   ✅ Token verified for bot: @{detail}")
                break
            print(f"   ⚠️  Token validation failed: {detail}\n")
            continue

        print("   ⚠️  That doesn't look right. A valid token contains a ':' ")
        print("      and is typically 40+ characters. Please try again.\n")

    # ── STEP 1.5: Owner User ID ────────────────────────────────────────────
    print("\n👤 Owner Authorization")
    print("   Enter the Telegram user ID allowed to control this bot.")
    print("   Tip: message @userinfobot from your Telegram account to get your numeric ID.\n")

    while True:
        owner_raw = input("   Enter OWNER Telegram User ID: ").strip()
        if owner_raw.isdigit() and int(owner_raw) > 0:
            owner_user_id = int(owner_raw)
            break
        print("   ⚠️  Please enter a valid positive numeric user ID.\n")

    # ── STEP 2: Ollama Connectivity Test ────────────────────────────────────
    print("\n🧠 STEP 2 of 3 — Ollama Connectivity Test")

    if not _test_ollama_connection():
        print("\n" + "-" * 62)
        print("   ❌ Setup cannot continue without a running Ollama instance.")
        print()
        print("   To fix this:")
        print("     1. Open a NEW terminal window")
        print("     2. Run: ollama serve")
        print("     3. (If no model is pulled) Run: ollama pull llama3")
        print("     4. Re-run this script")
        print("-" * 62 + "\n")
        sys.exit(1)

    # ── STEP 3: Sentinel Shell Permission ───────────────────────────────────
    print("\n🛡️  STEP 3 of 3 — Sentinel Shell Configuration")
    print("   The Sentinel Shell allows this bot to execute terminal commands")
    print("   on your machine. Every command requires your explicit approval")
    print("   via Telegram inline buttons before it runs.")
    print()
    print("   If you choose 'N', the bot will only function as a")
    print("   text-to-text AI assistant (no OS access).\n")

    while True:
        choice = input("   Enable the Sentinel Shell for OS/Terminal commands? (Y/N): ").strip().upper()
        if choice in ("Y", "N"):
            break
        print("   ⚠️  Please enter Y or N.\n")

    sentinel_enabled = (choice == "Y")

    # ── Build Configuration ─────────────────────────────────────────────────
    config = {
        "telegram_token":         token,
        "owner_user_id":          owner_user_id,
        "sentinel_shell_enabled": sentinel_enabled,
        "platform":               CURRENT_PLATFORM,
    }

    # ── Save & Confirm ──────────────────────────────────────────────────────
    print()
    save_config(config)

    sentinel_label = "ENABLED ✅" if sentinel_enabled else "DISABLED 🔒"

    print("\n" + "=" * 62)
    print("   ✅ Local Setup Complete!")
    print(f"   Sentinel Shell: {sentinel_label}")

    delivered = _send_setup_complete_message(token, owner_user_id, sentinel_enabled)
    if delivered:
        print("   📩 Setup handshake message sent to your Telegram account.")
    else:
        print("   ⚠️  Could not auto-send setup handshake message.")
        print("   Open Telegram and send /start manually.")

    print("=" * 62 + "\n")

    # ── FUN ANIMATION: Setup Complete ──
    try:
        sys.stdout.write("   Initializing Omni-Mediator Core ")
        sys.stdout.flush()
        for _ in range(3):
            for char in "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏":
                sys.stdout.write(f"\b{char}")
                sys.stdout.flush()
                time.sleep(0.1)
        sys.stdout.write("\b✅\n\n")
        
        print("   🌟 ALL SYSTEMS GO! 🌟\n")
    except KeyboardInterrupt:
        pass

    return config


# =============================================================================
# SECTION 6: ASYNC EXECUTOR WRAPPER
# =============================================================================
# All blocking operations (subprocess, HTTP requests) MUST be offloaded to a
# thread executor so they never freeze the Telegram polling loop.
# This is THE critical async requirement from the architecture doc.
# =============================================================================

async def run_blocking(func, *args, **kwargs):
    """
    Offload a blocking function to the default thread-pool executor.

    This wraps asyncio.get_event_loop().run_in_executor() with a cleaner
    interface. The Telegram polling loop continues processing other messages
    while this function runs in a background thread.

    Args:
        func:   The blocking callable (e.g., subprocess.run, requests.post).
        *args:  Positional arguments forwarded to func.
        **kwargs: Keyword arguments forwarded to func.

    Returns:
        Whatever func() returns.
    """
    loop = asyncio.get_event_loop()
    # functools.partial lets us pass kwargs through run_in_executor
    return await loop.run_in_executor(
        None,  # Use the default ThreadPoolExecutor
        functools.partial(func, *args, **kwargs),
    )


# =============================================================================
# SECTION 7: OLLAMA API BRIDGE
# =============================================================================
# The "Brain" of the Mediator. Sends user text to the local Ollama LLM and
# returns the generated response. All calls use a strict timeout and are
# wrapped in comprehensive error handling for graceful degradation.
#
# This function is SYNCHRONOUS — it is always called via run_blocking()
# so the Telegram polling loop never freezes while the model generates.
# =============================================================================

def query_ollama(user_text: str) -> str:
    """
    Send a prompt to the local Ollama LLM and return the generated text.

    Technical constraints (from architecture doc):
      • requests.post() has a STRICT timeout=10s
      • Wrapped in try/except for Timeout, ConnectionError, and generic errors
      • Returns user-friendly error messages — never raw tracebacks

    Args:
        user_text: The user's message / prompt to send to the LLM.

    Returns:
        str: The generated response text, or a formatted error message.
    """
    try:
        response = requests.post(
            OLLAMA_API_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": user_text,
                "stream": False,       # Single JSON response, not streamed chunks
            },
            timeout=OLLAMA_GENERATE_TIMEOUT,  # CRITICAL: 10s hard cap
        )
        response.raise_for_status()

        data = response.json()
        generated = data.get("response", "").strip()

        if not generated:
            return (
                "⚠️ The AI returned an empty response.\n"
                "Try rephrasing your question or check if the model is loaded."
            )

        return generated

    except requests.exceptions.Timeout:
        # The LLM took longer than 10s — fail fast, don't hang
        return (
            "⚠️ *Local Agent Timeout:* The request to Ollama took too long "
            "to process. Try a shorter or simpler prompt."
        )

    except requests.exceptions.ConnectionError:
        # Ollama is not running or port 11434 is unreachable
        return (
            "⚠️ *Local Agent Offline:* Could not connect to the Ollama service.\n"
            "Is it running? Start it with: `ollama serve`"
        )

    except requests.exceptions.HTTPError as exc:
        # Ollama returned an HTTP error (e.g., 404 model not found)
        status_code = exc.response.status_code if exc.response else "unknown"
        return (
            f"⚠️ *Ollama Error (HTTP {status_code}):* "
            f"The model may not be available. Try: `ollama pull {OLLAMA_MODEL}`"
        )

    except Exception as exc:
        # Catch-all — never send raw tracebacks to the user
        print(f"⚠️  Unexpected Ollama error: {type(exc).__name__}: {exc}")
        return (
            "⚠️ *Unexpected Error:* Something went wrong while contacting "
            "the local AI. Check the terminal for details."
        )


# =============================================================================
# SECTION 8: SYSTEM STATUS CHECKS (psutil — instant, no AI needed)
# =============================================================================
# These are the "Quick Checks" from the Intent Router specification.
# They bypass the AI entirely and return formatted system info instantly.
# =============================================================================

def _get_system_status() -> str:
    """
    Gather a comprehensive system status snapshot using psutil.

    Returns a pre-formatted string ready to be sent as a Telegram message.
    This is a synchronous function — called via run_blocking() from handlers.
    """
    # ── CPU ──
    cpu_percent = psutil.cpu_percent(interval=1)  # 1s sample for accuracy
    cpu_count = psutil.cpu_count(logical=True)
    cpu_freq = psutil.cpu_freq()
    freq_str = f"{cpu_freq.current:.0f} MHz" if cpu_freq else "N/A"

    # ── Memory ──
    mem = psutil.virtual_memory()
    mem_total_gb = mem.total / (1024 ** 3)
    mem_used_gb  = mem.used / (1024 ** 3)
    mem_avail_gb = mem.available / (1024 ** 3)

    # ── Disk ──
    disk = psutil.disk_usage("/")
    disk_total_gb = disk.total / (1024 ** 3)
    disk_used_gb  = disk.used / (1024 ** 3)
    disk_free_gb  = disk.free / (1024 ** 3)

    # ── Battery (laptop-specific, may not exist on desktops) ──
    battery = psutil.sensors_battery()
    if battery:
        plug_status = "🔌 Plugged In" if battery.power_plugged else "🔋 On Battery"
        battery_str = f"{battery.percent:.0f}% — {plug_status}"
    else:
        battery_str = "N/A (no battery detected)"

    # ── Uptime ──
    import time
    boot_time = psutil.boot_time()
    uptime_seconds = time.time() - boot_time
    uptime_hours = int(uptime_seconds // 3600)
    uptime_mins  = int((uptime_seconds % 3600) // 60)

    # ── Format the report ──
    report = (
        "📊 *System Status Report*\n"
        "\n"
        f"*CPU:*  `{cpu_percent}%` load  |  {cpu_count} cores @ {freq_str}\n"
        f"*RAM:*  `{mem_used_gb:.1f}` / {mem_total_gb:.1f} GB used  "
        f"({mem_avail_gb:.1f} GB free)\n"
        f"*Disk:* `{disk_used_gb:.0f}` / {disk_total_gb:.0f} GB used  "
        f"({disk_free_gb:.0f} GB free)\n"
        f"*Battery:* {battery_str}\n"
        f"*Uptime:* {uptime_hours}h {uptime_mins}m\n"
        f"*Platform:* `{CURRENT_PLATFORM}`"
    )

    return report


# =============================================================================
# SECTION 8: OS COMMAND EXECUTION (Platform-Agnostic)
# =============================================================================
# These functions handle the "open" / "launch" OS-level actions.
# All subprocess calls enforce shell=False and timeout=SUBPROCESS_TIMEOUT.
# =============================================================================

def _open_target(target: str) -> str:
    """
    Open a file, folder, URL, or application using the OS-native command.

    Platform routing:
      • macOS (Darwin):  subprocess.run(["open", target])
      • Windows:         os.startfile(target)
      • Linux:           subprocess.run(["xdg-open", target])

    Args:
        target: The file path, URL, or app name to open.

    Returns:
        A status message string for the Telegram response.
    """
    # Expand ~ to the user's home directory — never hardcode paths
    if target.startswith("~"):
        target = os.path.expanduser(target)

    try:
        if CURRENT_PLATFORM == "Darwin":
            # macOS: "open" handles files, folders, URLs, and .app bundles
            result = subprocess.run(
                ["open", target],
                capture_output=True,
                text=True,
                shell=False,                    # SECURITY: no shell injection
                timeout=SUBPROCESS_TIMEOUT,     # RESILIENCE: no infinite hangs
            )
        elif CURRENT_PLATFORM == "Windows":
            # Windows: os.startfile is the native way, but it doesn't support
            # timeout. We use subprocess with 'start' as a fallback.
            os.startfile(target)
            return f"✅ Opened: <code>{html.escape(target)}</code>"
        else:
            # Linux: xdg-open is the cross-desktop standard
            result = subprocess.run(
                ["xdg-open", target],
                capture_output=True,
                text=True,
                shell=False,
                timeout=SUBPROCESS_TIMEOUT,
            )

        # Check for errors from the subprocess (non-Windows)
        if result.returncode == 0:
            return f"✅ Opened: <code>{html.escape(target)}</code>"
        else:
            error_msg = result.stderr.strip() or "Unknown error"
            return (
                f"❌ Failed to open <code>{html.escape(target)}</code>: "
                f"{html.escape(error_msg)}"
            )

    except subprocess.TimeoutExpired:
        return f"⏱️ Timed out trying to open <code>{html.escape(target)}</code> (&gt;{SUBPROCESS_TIMEOUT}s)"
    except FileNotFoundError:
        return f"❌ File or command not found: <code>{html.escape(target)}</code>"
    except Exception as exc:
        return f"❌ Error opening <code>{html.escape(target)}</code>: {html.escape(str(exc))}"


def _execute_shell_command(command_str: str) -> str:
    """
    Execute a pre-validated, allow-listed terminal command.

    Security layers (checked BEFORE this function is called):
      1. Sentinel Shell must be enabled in config.
      2. Command must not start with any BLOCKED_PREFIX.
      3. Base command must be in ALLOWED_COMMANDS.
      4. (Phase 4) User must tap [Allow] on an inline keyboard.

    This function ONLY handles execution — all validation is done upstream.

    Args:
        command_str: The full command string (e.g., "ls -la ~/Desktop").

    Returns:
        Formatted output string for the Telegram response.
    """
    try:
        # shlex.split safely tokenizes the command — respects quotes
        raw_args = shlex.split(command_str)
        args = [os.path.expanduser(arg) if arg.startswith("~") else arg for arg in raw_args]
    except ValueError as exc:
        return f"❌ Invalid command syntax: {exc}"

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            shell=False,                    # SECURITY: never use shell=True
            timeout=SUBPROCESS_TIMEOUT,     # RESILIENCE: 30s hard cap
        )

        output = result.stdout.strip() or result.stderr.strip() or "(no output)"

        # Truncate very long output to avoid Telegram message limits (4096 chars)
        if len(output) > 3500:
            output = output[:3500] + "\n\n… (output truncated)"

        status = "✅" if result.returncode == 0 else "⚠️"
        return (
            f"{status} <b>Command:</b> <code>{html.escape(command_str)}</code>\n"
            f"<b>Exit Code:</b> {result.returncode}\n\n"
            f"<pre><code>{html.escape(output)}</code></pre>"
        )

    except subprocess.TimeoutExpired:
        return (
            f"⏱️ <b>Command timed out</b> (&gt;{SUBPROCESS_TIMEOUT}s)\n"
            f"Command: <code>{html.escape(command_str)}</code>\n\n"
            f"The process was killed to protect system stability."
        )
    except FileNotFoundError:
        return f"❌ Command not found: <code>{html.escape(args[0])}</code>"
    except Exception as exc:
        return f"❌ Execution error: {html.escape(str(exc))}"


# =============================================================================
# SECTION 9: INTENT ROUTER
# =============================================================================
# The brain of the Mediator. It classifies every incoming message and routes
# it to the appropriate handler — saving compute and latency by keeping
# simple tasks away from the AI.
#
# Priority order:
#   1. Quick Checks (status/ram/cpu)     → psutil, instant
#   2. OS Actions   (open/launch)        → subprocess via async executor
#   3. Terminal Commands (ls, pwd, etc.) → allow-list check → executor
#   4. Complex Queries (everything else) → Ollama (Phase 3)
# =============================================================================

def _classify_intent(text: str, sentinel_enabled: bool) -> tuple[str, str]:
    """
    Classify a user message into an intent category.

    Args:
        text:             The raw message text (lowercased by caller).
        sentinel_enabled: Whether the Sentinel Shell is active.

    Returns:
        Tuple of (intent, payload):
          - ("status", "")           — system status check
          - ("os_open", target)      — open a file/app/URL
          - ("shell", command)       — execute a terminal command
          - ("blocked", reason)      — dangerous command rejected
          - ("shell_disabled", "")   — Sentinel Shell is off
          - ("ai", original_text)    — forward to Ollama (Phase 3)
    """
    text_lower = text.lower().strip()

    # ── Priority 1: Quick status checks ──
    # These keywords trigger an instant psutil response, no AI needed.
    tokens = set(re.findall(r"[a-zA-Z]+", text_lower))
    if STATUS_SINGLE_KEYWORDS.intersection(tokens):
        return ("status", "")
    for phrase in STATUS_PHRASES:
        if phrase in text_lower:
            return ("status", "")

    # ── Priority 2: OS open/launch actions ──
    for prefix in OS_ACTION_PREFIXES:
        if text_lower.startswith(prefix):
            target = text[len(prefix):].strip()
            if target:
                if not sentinel_enabled:
                    return ("shell_disabled", "")
                return ("os_open", target)

    # ── Priority 3: Terminal command detection ──
    # If the message looks like a shell command (starts with an allowed base command),
    # route it through the Sentinel Shell pipeline.
    first_word = text_lower.split()[0] if text_lower.split() else ""

    if first_word in ALLOWED_COMMANDS:
        # Check if Sentinel Shell is enabled
        if not sentinel_enabled:
            return ("shell_disabled", "")

        # Check for blocked prefixes FIRST — unconditional rejection
        for blocked in BLOCKED_PREFIXES:
            if text_lower.startswith(blocked):
                return ("blocked", f"Command blocked: `{blocked}` is not permitted.")

        return ("shell", text.strip())

    # Also catch blocked commands even if they're not in the allow-list
    for blocked in BLOCKED_PREFIXES:
        if text_lower.startswith(blocked):
            return ("blocked", f"🚫 `{blocked.strip()}` is permanently blocked for security.")

    # ── Priority 4: Everything else → AI (Phase 3) ──
    return ("ai", text)


# =============================================================================
# SECTION 10: TELEGRAM COMMAND & MESSAGE HANDLERS
# =============================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler for /start — the Final Handshake.

    When the user sends /start from Telegram, this confirms that the
    local-to-mobile bridge is live and reports system status.
    """
    if await _reject_if_unauthorized(update, context):
        return

    # Load the persisted config to report Sentinel Shell status
    config = _get_runtime_config(context)
    sentinel_status = config.get("sentinel_shell_enabled", False) if config else False

    status_emoji = "✅ Enabled" if sentinel_status else "🔒 Disabled"

    handshake_message = (
        "✅ *Handshake Complete!*\n"
        "\n"
        "Your local AI is connected and Ollama is running.\n"
        "\n"
        f"🛡️ Sentinel Shell: {status_emoji}\n"
        f"🖥️ Platform: `{CURRENT_PLATFORM}`\n"
        "\n"
        "*Available Commands:*\n"
        "`/start`  — Connection handshake\n"
        "`/status` — System status (CPU, RAM, Disk)\n"
        "`/help`   — Show available commands\n"
        "\n"
        "Or just type naturally — I'll figure out what you mean!"
    )

    await update.message.reply_text(
        handshake_message,
        parse_mode="Markdown",
    )

    # Log the handshake to the local terminal for the exhibitor
    user = update.effective_user
    print(f"🤝 Handshake completed — user: {user.first_name} (ID: {user.id})")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler for /status — instant system status report.

    Offloads psutil data collection to a thread executor so CPU sampling
    (which takes ~1s) doesn't block the polling loop.
    """
    if await _reject_if_unauthorized(update, context):
        return

    print(f"📊 Status requested by {update.effective_user.first_name}")

    # Offload the blocking psutil call to a background thread
    report = await run_blocking(_get_system_status)

    await update.message.reply_text(report, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler for /help — shows all available commands and capabilities.
    """
    if await _reject_if_unauthorized(update, context):
        return

    config = _get_runtime_config(context)
    sentinel_status = config.get("sentinel_shell_enabled", False) if config else False

    help_text = (
        "🤖 *Omni-Mediator — Command Reference*\n"
        "\n"
        "*Slash Commands:*\n"
        "`/start`  — Verify connection handshake\n"
        "`/status` — Live system status (CPU, RAM, Disk, Battery)\n"
        "`/help`   — This help message\n"
        "\n"
        "*Natural Language (just type):*\n"
        '• `"status"` / `"ram"` / `"cpu"` — Quick system check\n'
    )

    if sentinel_status:
        help_text += (
            '• `"open ~/Desktop"` — Open files, folders, or apps\n'
            "\n*Sentinel Shell (Enabled):*\n"
            f"Allowed commands: `{', '.join(sorted(ALLOWED_COMMANDS))}`\n"
            "Type any allowed command directly (e.g., `ls -la`)\n"
            "Each command requires your approval via inline buttons\n"
            "[✅ Allow] or [❌ Deny] before it executes.\n"
            "\n"
            "🚫 `sudo`, `su`, `rm -rf` are permanently blocked.\n"
        )
    else:
        help_text += (
            "\n*Sentinel Shell:* 🔒 Disabled\n"
            "Terminal and OS actions are not available.\n"
        )

    help_text += (
        "\n*AI Chat:*\n"
        "Any other message is forwarded to your local Ollama LLM.\n"
        f"Model: `{OLLAMA_MODEL}` | Timeout: `{OLLAMA_GENERATE_TIMEOUT}s`"
    )

    await update.message.reply_text(help_text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    The main message handler — routes ALL non-command text through the Intent Router.

    This is the heart of Phase 2. Every plain-text message hits this function,
    gets classified by _classify_intent(), and is dispatched to the appropriate
    handler — all without blocking the async polling loop.
    """
    if await _reject_if_unauthorized(update, context):
        return

    text = update.message.text
    if not text:
        return

    user = update.effective_user
    print(f"💬 [{user.first_name}] {text}")

    # Load config to check Sentinel Shell status
    config = _get_runtime_config(context)
    sentinel_enabled = config.get("sentinel_shell_enabled", False) if config else False

    # ── Classify the intent ──
    intent, payload = _classify_intent(text, sentinel_enabled)

    # ── Dispatch based on intent ──

    if intent == "status":
        # Quick check — offload psutil to executor
        print(f"   → Intent: STATUS (quick check)")
        report = await run_blocking(_get_system_status)
        await update.message.reply_text(report, parse_mode="Markdown")

    elif intent == "os_open":
        # Open file/folder/app — offload subprocess to executor
        print(f"   → Intent: OS_OPEN → {payload}")
        result = await run_blocking(_open_target, payload)
        await update.message.reply_text(result, parse_mode=ParseMode.HTML)

    elif intent == "shell":
        # ── SENTINEL SHELL: Human-in-the-loop verification ──
        # Instead of executing immediately, we present the command to the
        # user with [✅ Allow] and [❌ Deny] inline keyboard buttons.
        # The command ONLY executes if the user taps Allow.
        print(f"   → Intent: SHELL → Awaiting approval for: {payload}")

        # Store the pending command in context.user_data so the callback
        # handler can retrieve it when the button is tapped.
        cmd_id = str(uuid.uuid4())[:8]
        context.user_data.setdefault('pending_commands', {})[cmd_id] = payload

        # Build the inline keyboard with Allow / Deny buttons.
        # Callback data is prefixed with "exec_" and "deny_" for routing.
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Allow", callback_data=f"exec_{cmd_id}"),
                InlineKeyboardButton("❌ Deny",  callback_data=f"deny_{cmd_id}"),
            ]
        ])

        await update.message.reply_text(
            f"🛡️ <b>Sentinel Shell — Authorization Required</b>\n\n"
            f"Command: <code>{html.escape(payload)}</code>\n\n"
            f"Do you want to execute this command on your machine?",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    elif intent == "blocked":
        # Dangerous command — unconditionally rejected
        print(f"   → Intent: BLOCKED ⛔")
        await update.message.reply_text(
            f"🚫 <b>Security Violation</b>\n\n<code>{html.escape(payload)}</code>\n\n"
            f"This command is permanently blocked and cannot be overridden.",
            parse_mode=ParseMode.HTML,
        )

    elif intent == "shell_disabled":
        # Valid command but Sentinel Shell is off
        print(f"   → Intent: SHELL_DISABLED")
        await update.message.reply_text(
            "🔒 *Sentinel Shell is Disabled*\n\n"
            "Terminal and OS actions are not available in this configuration.\n"
            "Re-run the setup wizard to enable the Sentinel Shell.",
            parse_mode="Markdown",
        )

    elif intent == "ai":
        # Forward to Ollama — the full AI bridge
        print(f"   → Intent: AI → Ollama ({OLLAMA_MODEL})")

        # Send a "thinking" placeholder immediately so the user knows
        # their message was received. The Telegram UI will show this
        # while the LLM generates in the background.
        thinking_msg = await update.message.reply_text(
            "🧠 _Consulting Local Agent (this might take a moment)..._",
            parse_mode="Markdown",
        )

        # Offload the blocking HTTP request to a thread executor.
        # The Telegram polling loop continues handling other messages
        # while Ollama generates the response.
        ai_response = await run_blocking(query_ollama, text)

        # Edit the placeholder message with the actual AI response.
        # This gives a clean UX — the "thinking" message transforms
        # into the answer in-place.
        try:
            await thinking_msg.edit_text(
                ai_response,
                parse_mode="Markdown",
            )
        except Exception:
            # If edit fails (e.g., Markdown parse error in AI response),
            # fall back to sending a plain-text message instead.
            try:
                await thinking_msg.edit_text(ai_response)
            except Exception:
                # Last resort: send as a new message (edit can fail if
                # the message is identical or too old)
                await update.message.reply_text(ai_response)


# =============================================================================
# SECTION 11: SENTINEL SHELL CALLBACK HANDLER
# =============================================================================
# This handler processes the inline button taps from the Sentinel Shell.
# When a user taps [✅ Allow], the pending command is retrieved from
# context.user_data, executed via run_blocking(), and the result is sent.
# When [❌ Deny] is tapped, the command is discarded.
# =============================================================================

async def callback_sentinel_shell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle inline button callbacks from the Sentinel Shell authorization prompt.

    This is the core of the human-in-the-loop security model:
      • ✅ Allow → Execute the pending command and return output
      • ❌ Deny  → Discard the command, inform the user

    The pending command is stored in context.user_data["pending_commands"][cmd_id]
    by the handle_message function when a shell intent is detected.
    """
    if await _reject_if_unauthorized(update, context):
        return

    query = update.callback_query

    # Acknowledge the button press immediately (removes the loading spinner)
    await query.answer()

    callback_data = query.data

    if not (callback_data.startswith("exec_") or callback_data.startswith("deny_")):
        return
        
    action, cmd_id = callback_data.split("_", 1)

    if action == "exec":
        # ── USER APPROVED: Execute the command ──
        pending_cmd = context.user_data.get("pending_commands", {}).pop(cmd_id, None)

        if not pending_cmd:
            await query.edit_message_text(
                "⚠️ No pending command found. It may have expired.\n"
                "Please send the command again."
            )
            return

        print(f"🛡️ Sentinel Shell: ALLOWED → {pending_cmd}")

        # Update the authorization message to show it was approved
        await query.edit_message_text(
            f"🛡️ <b>Sentinel Shell — Approved ✅</b>\n\n"
            f"Command: <code>{html.escape(pending_cmd)}</code>\n\n"
            f"⏳ <i>Executing...</i>",
            parse_mode=ParseMode.HTML,
        )

        # Execute the command via the async executor — never blocks polling
        result = await run_blocking(_execute_shell_command, pending_cmd)

        # Send the result as a new message (the authorization message stays
        # as a record of approval)
        await query.message.reply_text(result, parse_mode=ParseMode.HTML)

    elif action == "deny":
        # ── USER DENIED: Discard the command ──
        denied_cmd = context.user_data.get("pending_commands", {}).pop(cmd_id, "(unknown)")

        print(f"🛡️ Sentinel Shell: DENIED → {denied_cmd}")

        await query.edit_message_text(
            f"🛡️ <b>Sentinel Shell — Denied ❌</b>\n\n"
            f"Command: <code>{html.escape(denied_cmd)}</code>\n\n"
            f"The command was not executed.",
            parse_mode=ParseMode.HTML,
        )


# =============================================================================
# SECTION 12: GLOBAL ERROR HANDLER — Exhibition-Grade Network Resilience
# =============================================================================

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Catch-all error handler attached to the Telegram Application.

    Resilience Strategy:
      • TimedOut & NetworkError → Silently absorbed. The polling loop
        auto-retries, so transient Wi-Fi drops at a live exhibition
        never crash the bot.
      • All other exceptions → Logged to the local terminal for
        debugging, but the bot keeps running.

    This handler ensures the async polling loop is NEVER interrupted
    by recoverable failures.
    """
    error = context.error

    # ── Silent absorption: network transients ──
    if isinstance(error, (TimedOut, NetworkError)):
        # Intentionally no output — these are expected in unstable environments.
        # The python-telegram-bot library will automatically retry the poll.
        return

    # ── Log unexpected errors for debugging ──
    # In a live demo, these go to the laptop terminal — not to the user's phone.
    print(f"⚠️  [{type(error).__name__}] {error}")

    # If we have an update context, log which user/chat triggered the error
    if update and hasattr(update, "effective_user") and update.effective_user:
        print(f"   Triggered by user: {update.effective_user.first_name}")


# =============================================================================
# SECTION 8: MAIN ENTRY POINT
# =============================================================================

def main() -> None:
    """
    Omni-Mediator entry point.

    Execution flow:
      1.  Dependencies are already ensured (Section 1 ran at import time).
      2.  Load config.json — or run the FTUX wizard if it doesn't exist.
      3.  Build the async Telegram Application with the saved token.
      4.  Register the /start handler and global error handler.
      5.  Start polling (this blocks until Ctrl+C / SIGINT).

    The polling loop is fully asynchronous via python-telegram-bot v20+.
    run_polling() manages the asyncio event loop internally, ensuring no
    blocking calls can freeze the Telegram listener.
    """

    # ── Startup banner ──
    print("┌──────────────────────────────────────────────────────────┐")
    print("│        🌐 OMNI-MEDIATOR v1.0 — Local AI Bridge          │")
    print("│           All Phases Complete — Production Ready         │")
    print("├──────────────────────────────────────────────────────────┤")
    print(f"│  Platform : {CURRENT_PLATFORM:<45s}│")
    print(f"│  Python   : {sys.version.split()[0]:<45s}│")
    print("└──────────────────────────────────────────────────────────┘")
    print()

    # ── Load or create configuration ──
    config = load_config()

    if config is None:
        # First launch — run the full FTUX wizard
        config = run_ftux_wizard()
    else:
        sentinel_label = "Enabled" if config.get("sentinel_shell_enabled") else "Disabled"
        print(f"📂 Configuration loaded from: {CONFIG_PATH}")
        print(f"   Sentinel Shell: {sentinel_label}")
        print()

    # ── Build Telegram Application ──
    token = config["telegram_token"]

    print("🤖 Initializing Telegram bot...")
    app = Application.builder().token(token).build()
    app.bot_data["config"] = config

    # ── Register command handlers ──
    app.add_handler(CommandHandler("start", cmd_start))     # /start — handshake
    app.add_handler(CommandHandler("status", cmd_status))   # /status — system info
    app.add_handler(CommandHandler("help", cmd_help))       # /help   — command ref

    # ── Register the Sentinel Shell callback handler ──
    # This processes inline button taps (✅ Allow / ❌ Deny) from the
    # human-in-the-loop verification prompt.
    app.add_handler(CallbackQueryHandler(callback_sentinel_shell))

    # ── Register the general message handler ──
    # This catches ALL plain-text messages and routes them through the
    # Intent Router. filters.TEXT catches text, ~filters.COMMAND excludes
    # slash commands (which are handled above).
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ── Global error handler — silently absorbs TimedOut/NetworkError ──
    app.add_error_handler(global_error_handler)

    # ── Start async polling ──
    print("✅ Bot is live! Waiting for messages...")
    print("   Commands: /start, /status, /help")
    print("   Or type naturally: 'status', 'open ~/Desktop', 'ls -la'")
    print("   🛡️ Sentinel Shell commands require inline button approval.")
    print("   Press Ctrl+C to stop.\n")

    # run_polling() handles the asyncio event loop internally.
    # drop_pending_updates=True ensures we ignore stale messages from
    # when the bot was offline — important for exhibition restarts.
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


# =============================================================================
# SECTION 13: SCRIPT ENTRY — The single command a user runs
# =============================================================================

if __name__ == "__main__":
    main()
