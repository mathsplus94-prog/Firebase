#!/usr/bin/env python3
# firebaseXfacher.py
# Ujala Auto — Multi-User Independent Session Bot

import telebot
import requests
import threading
import json
import os
import re
import time
import base64
import urllib.parse
import concurrent.futures
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ============================================================
# CONFIG
# ============================================================
BOT_TOKEN = "8953630903:AAG2v22_3fDc4SvfNc59YPcyOdi2zot0KRg"
ALLOWED_IDS = [
    6297919814,   # Ayush (admin)
    # 123456789,  # aur admin add karna ho to
]

BASE_DIR = "users_data"
USERS_FILE = "users.json"
REPORT_FILE = "report.txt"
DEVICE_REPORT_FILE = "device_report.txt"
SCAN_REPORT_FILE = "scan_report.txt"
AUTO_CHECK_INTERVAL = 3600

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/146.0.0.0 Safari/537.36",
}
SHALLOW_TIMEOUT = 8
FULL_TIMEOUT = 20
DEVICE_TIMEOUT = 10
SCAN_TIMEOUT = 10

DEVICE_PATHS = [
    "clients", "devices", "DeviceInfo", "Device_Info", "device_info",
    "All_Users/Data/DeviceInfo", "All_Users/clients", "All_Users/Data",
    "All_Users", "users", "Users", "user_data", "userData",
    "registeredDevices", "registered_devices", "activeDevices",
    "onlineDevices", "deviceList", "device_list", "tokens",
    "fcmTokens", "FCM_Tokens", "connections", "sessions",
    "app_data", "appData", "data/devices", "data/clients",
    "data/users", "data/DeviceInfo", "info/devices",
    "root/devices", "panel/devices", "bot/devices",
]

STATUS_KEYS = [
    "status", "Status", "online", "Online", "is_online", "isOnline",
    "active", "Active", "isActive", "connected", "Connected",
    "isConnected", "state", "State", "power", "Power",
    "is_active", "is_active_status", "user_status",
    "isOnlineStatus", "online_status", "onlineStatus",
    "device_status", "deviceStatus", "userStatus",
]

LASTSEEN_KEYS = [
    "lastSeen", "last_seen", "lastActive", "last_active", "lastOnline",
    "last_online", "updatedAt", "updated_at", "timestamp", "time",
    "lastUpdate", "last_update", "lastPing", "last_ping", "seen",
    "date", "Date", "lastSeenTime", "last_seen_time",
    "last_seen_at", "lastActiveTime", "last_active_time",
    "last_online_time", "lastOnlineTime", "lastConnected",
    "last_connected", "pingTime", "ping_time",
]

FIREBASE_PATTERNS = [
    r'https?://[a-z0-9\-]+-default-rtdb\.firebaseio\.com',
    r'https?://[a-z0-9\-]+-default-rtdb\.[a-z0-9\-]+\.firebasedatabase\.app',
    r'https?://[a-z0-9\-]+\.firebaseio\.com',
    r'https?://[a-z0-9\-]+\.firebasedatabase\.app',
]

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=True, num_threads=40)
file_lock = threading.Lock()
user_locks = {}
user_locks_lock = threading.Lock()


def get_user_lock(uid):
    with user_locks_lock:
        if uid not in user_locks:
            user_locks[uid] = threading.Lock()
        return user_locks[uid]


# ============================================================
# ADMIN CHECK
# ============================================================
def is_admin(uid):
    return int(uid) in ALLOWED_IDS


# ============================================================
# PER-USER STORAGE
# ============================================================
def user_dir(uid):
    d = os.path.join(BASE_DIR, str(uid))
    os.makedirs(d, exist_ok=True)
    return d


def user_panels_file(uid):
    return os.path.join(user_dir(uid), "panels.json")


def user_dumps_dir(uid):
    d = os.path.join(user_dir(uid), "dumps")
    os.makedirs(d, exist_ok=True)
    return d


def load_user_panels(uid):
    f = user_panels_file(uid)
    if os.path.exists(f):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                if isinstance(data, list):
                    return [u.strip().rstrip("/") for u in data if u.strip()]
        except Exception:
            pass
    return []


def save_user_panels(uid, panels):
    lock = get_user_lock(uid)
    with lock:
        with open(user_panels_file(uid), "w", encoding="utf-8") as f:
            json.dump(panels, f, indent=2, ensure_ascii=False)


def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def save_users(users):
    with file_lock:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)


USERS = load_users()


def track_user(message):
    try:
        uid = str(message.from_user.id)
        name = ((message.from_user.first_name or "") + " " +
                (message.from_user.last_name or "")).strip()
        uname = message.from_user.username or ""
        USERS[uid] = {
            "name": name,
            "username": uname,
            "last_seen": datetime.now().isoformat(),
        }
        save_users(USERS)
    except Exception:
        pass


def all_users_with_panels():
    """Admin ke liye — sab users ki list"""
    result = {}
    if not os.path.isdir(BASE_DIR):
        return result
    for uid in os.listdir(BASE_DIR):
        panels = load_user_panels(uid)
        if panels:
            result[uid] = panels
    return result


# ============================================================
# HELPERS
# ============================================================
def short_name(url):
    s = url.replace("https://", "").replace("http://", "")
    for suf in ["-default-rtdb.firebaseio.com",
                "-default-rtdb.asia-southeast1.firebasedatabase.app",
                ".firebaseio.com", ".firebasedatabase.app"]:
        s = s.replace(suf, "")
    return s.replace("/", "_").strip("_")[:40]


def safe_get(url, timeout):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code != 200:
            return r.status_code, None, r.text[:200]
        try:
            return 200, r.json(), None
        except Exception:
            return 200, None, r.text[:200]
    except requests.exceptions.Timeout:
        return "timeout", None, f"timeout {timeout}s"
    except requests.exceptions.ConnectionError as e:
        return "dns", None, str(e)[:100]
    except Exception as e:
        return "err", None, str(e)[:100]


def extract_urls(text):
    if not text:
        return []
    urls = re.findall(r'https?://[^\s"\'<>]+', text)
    out = []
    for u in urls:
        u = u.strip().rstrip("/")
        if "firebaseio.com" in u or "firebasedatabase.app" in u:
            out.append(u)
    seen = set()
    final = []
    for u in out:
        if u not in seen:
            seen.add(u)
            final.append(u)
    return final


# ============================================================
# PROBE
# ============================================================
def probe_panel(url):
    res = {"url": url, "short": short_name(url), "status": None,
           "keys": [], "count": 0, "verdict": "UNKNOWN", "error": None}
    st, data, err = safe_get(f"{url}/.json?shallow=true", SHALLOW_TIMEOUT)
    res["status"] = st
    if st == 200 and isinstance(data, dict):
        res["keys"] = list(data.keys())
        res["count"] = len(data)
        res["verdict"] = "OPEN"
    elif st == 423:
        res["verdict"] = "DEACTIVATED"
    elif st in (401, 403):
        res["verdict"] = "LOCKED"
    elif st == 404:
        res["verdict"] = "DEAD"
    elif st in ("timeout", "dns", "err"):
        res["verdict"] = "DEAD"
    else:
        res["verdict"] = f"HTTP {st}"
    if err:
        res["error"] = err
    return res


def full_dump(uid, url):
    dumps = user_dumps_dir(uid)
    st, data, err = safe_get(f"{url}/.json", FULL_TIMEOUT)
    if st != 200 or not isinstance(data, dict):
        return None, 0, err or f"status={st}"
    path = os.path.join(dumps, f"{short_name(url)}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path, os.path.getsize(path), None
    except Exception as e:
        return None, 0, str(e)


# ============================================================
# DEVICE CHECKER
# ============================================================
def is_online_true(val):
    if val is True: return True
    if isinstance(val, str) and val.lower() in ("true", "online", "1", "yes", "active", "on"): return True
    if isinstance(val, (int, float)) and val == 1: return True
    return False


def is_online_false(val):
    if val is False: return True
    if isinstance(val, str) and val.lower() in ("false", "offline", "0", "no", "inactive", "off"): return True
    if isinstance(val, (int, float)) and val == 0: return True
    return False


def check_device_status(device_data):
    if not isinstance(device_data, dict):
        return None
    for key in STATUS_KEYS:
        if key in device_data:
            val = device_data[key]
            if is_online_true(val): return True
            if is_online_false(val): return False
    for sub in ("data", "info", "device", "Device", "details", "status_info"):
        if sub in device_data and isinstance(device_data[sub], dict):
            for key in STATUS_KEYS:
                if key in device_data[sub]:
                    val = device_data[sub][key]
                    if is_online_true(val): return True
                    if is_online_false(val): return False
    now = time.time()
    for key in LASTSEEN_KEYS:
        if key in device_data:
            val = device_data[key]
            ts = None
            if isinstance(val, (int, float)):
                ts = val / 1000 if val > 1e12 else val
            elif isinstance(val, str):
                try:
                    f = float(val)
                    ts = f / 1000 if f > 1e12 else f
                except Exception:
                    pass
            if ts:
                if (now - ts) < 300:
                    return True
                return False
    for k, v in device_data.items():
        if isinstance(v, bool):
            if "online" in k.lower() or "active" in k.lower() or "status" in k.lower():
                return v
    return None


def discover_device_paths(url, timeout=DEVICE_TIMEOUT):
    paths = []
    try:
        r = requests.get(f"{url}/.json?shallow=true", headers=HEADERS, timeout=timeout)
        if r.status_code != 200:
            return paths
        root = r.json()
        if not isinstance(root, dict):
            return paths
        keywords = ["device", "client", "user", "token", "session",
                    "connection", "active", "online", "all_users"]
        for k in root.keys():
            kl = k.lower()
            if any(kw in kl for kw in keywords):
                paths.append(k)
        for k in list(root.keys())[:10]:
            for sub in ["devices", "clients", "users", "DeviceInfo", "data"]:
                paths.append(f"{k}/{sub}")
    except Exception:
        pass
    return paths


def fetch_panel_devices(url, timeout=DEVICE_TIMEOUT):
    result = {"url": url, "short": short_name(url), "status": None,
              "total": 0, "online": 0, "offline": 0, "unknown": 0,
              "path_used": None, "error": None}
    try:
        r = requests.get(f"{url}/.json?shallow=true", headers=HEADERS, timeout=timeout)
        result["status"] = r.status_code
        if r.status_code != 200:
            result["error"] = f"root {r.status_code}"
            return result
    except Exception as e:
        result["status"] = "err"
        result["error"] = str(e)[:80]
        return result
    all_paths = list(DEVICE_PATHS)
    try:
        all_paths += discover_device_paths(url, timeout)
    except Exception:
        pass
    best_path = None
    best_devices = {}
    for path in all_paths:
        try:
            r = requests.get(f"{url}/{path}.json", headers=HEADERS, timeout=timeout)
            if r.status_code != 200:
                continue
            data = r.json()
            if isinstance(data, dict) and data:
                sample = next(iter(data.values()))
                if isinstance(sample, dict):
                    if len(data) > len(best_devices):
                        best_path = path
                        best_devices = data
        except Exception:
            continue
    if not best_devices:
        result["error"] = "no device registry"
        return result
    result["path_used"] = best_path
    result["total"] = len(best_devices)
    for dev_id, dev_data in best_devices.items():
        status = check_device_status(dev_data)
        if status is True:
            result["online"] += 1
        elif status is False:
            result["offline"] += 1
        else:
            result["unknown"] += 1
    return result


# ============================================================
# SCANNER (encoded URL / website)
# ============================================================
def decode_base64_safe(s):
    try:
        pad = '=' * (-len(s) % 4)
        return base64.b64decode(s + pad).decode('utf-8', errors='ignore')
    except Exception:
        try:
            pad = '=' * (-len(s) % 4)
            return base64.urlsafe_b64decode(s + pad).decode('utf-8', errors='ignore')
        except Exception:
            return ""


def extract_from_text(text):
    found = set()
    for pat in FIREBASE_PATTERNS:
        for m in re.findall(pat, text, re.I):
            found.add(m.rstrip('/').rstrip('"').rstrip("'"))
    return found


def scan_url_for_firebase(full_url, timeout=SCAN_TIMEOUT):
    found = set()
    parsed = None
    try:
        parsed = urllib.parse.urlparse(full_url)
        qs = urllib.parse.parse_qs(parsed.query)
        for key in ('s', 'm', 'url', 'data', 'q', 'u', 'redirect', 'link'):
            if key in qs:
                for val in qs[key]:
                    decoded = decode_base64_safe(val)
                    if decoded:
                        found |= extract_from_text(decoded)
                        try:
                            j = json.loads(decoded)
                            if isinstance(j, list):
                                for item in j:
                                    if isinstance(item, dict) and 'url' in item:
                                        found |= extract_from_text(str(item['url']))
                            elif isinstance(j, dict) and 'url' in j:
                                found |= extract_from_text(str(j['url']))
                        except Exception:
                            pass
                    found |= extract_from_text(val)
    except Exception:
        pass
    found |= extract_from_text(full_url)
    if parsed and parsed.scheme in ('http', 'https') and parsed.netloc:
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        for target in [base, full_url]:
            try:
                r = requests.get(target, headers=HEADERS, timeout=timeout)
                if r.status_code == 200:
                    found |= extract_from_text(r.text)
                    js_links = re.findall(r'<script[^>]+src=["\']([^"\']+\.js)["\']', r.text)
                    for js in js_links[:5]:
                        try:
                            js_url = urllib.parse.urljoin(target, js)
                            jr = requests.get(js_url, headers=HEADERS, timeout=timeout)
                            found |= extract_from_text(jr.text)
                        except Exception:
                            continue
                    break
            except Exception:
                continue
    return sorted(found)


# ============================================================
# KEYBOARDS
# ============================================================
def main_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🔍 Check Devices", callback_data="btn_check_devices"),
        InlineKeyboardButton("📋 My Panels", callback_data="btn_my_panels"),
    )
    kb.add(
        InlineKeyboardButton("➕ Add Panel", callback_data="btn_add_panel"),
        InlineKeyboardButton("🧹 Clean Dead", callback_data="btn_clean"),
    )
    kb.add(
        InlineKeyboardButton("📊 Stats", callback_data="btn_stats"),
        InlineKeyboardButton("🆔 My ID", callback_data="btn_myid"),
    )
    kb.add(
        InlineKeyboardButton("🗑 Clear All", callback_data="btn_clear"),
    )
    return kb


# ============================================================
# COMMANDS
# ============================================================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    track_user(message)
    uid = message.from_user.id
    panels = load_user_panels(uid)
    text = (
        f"🔥 <b>UJALA AUTO</b>\n\n"
        f"👤 <b>Welcome {message.from_user.first_name or 'User'}!</b>\n\n"
        f"📦 Your panels: <b>{len(panels)}</b>\n"
        f"🆔 Your ID: <code>{uid}</code>\n\n"
        f"👇 <b>Neeche button tap karo</b>"
    )
    bot.send_message(message.chat.id, text, reply_markup=main_keyboard())


@bot.message_handler(commands=['myid'])
def cmd_myid(message):
    track_user(message)
    bot.reply_to(message,
        f"🆔 <b>Your Telegram ID:</b> <code>{message.from_user.id}</code>")


# ============================================================
# BUTTON HANDLERS
# ============================================================
@bot.callback_query_handler(func=lambda c: c.data == "btn_myid")
def cb_myid(call):
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id,
        f"🆔 <b>Your ID:</b> <code>{call.from_user.id}</code>")


@bot.callback_query_handler(func=lambda c: c.data == "btn_my_panels")
def cb_my_panels(call):
    bot.answer_callback_query(call.id)
    panels = load_user_panels(call.from_user.id)
    if not panels:
        bot.send_message(call.message.chat.id,
            "📭 <b>Tere paas koi panel nahi hai.</b>\n\n"
            "➕ <b>Add Panel</b> button tap karke add kar.")
        return
    lines = [f"📋 <b>YOUR PANELS ({len(panels)})</b>\n"]
    for i, u in enumerate(panels, 1):
        lines.append(f"{i}. <code>{u}</code>")
    out = "\n".join(lines)
    for chunk in [out[i:i+3800] for i in range(0, len(out), 3800)]:
        bot.send_message(call.message.chat.id, chunk, disable_web_page_preview=True)


@bot.callback_query_handler(func=lambda c: c.data == "btn_add_panel")
def cb_add_panel(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id,
        "📥 <b>Panel add karo:</b>\n\n"
        "• URLs paste karo (space/newline)\n"
        "• Ya <code>.txt</code> file bhejo\n\n"
        "<i>Cancel ke liye /cancel</i>")
    bot.register_next_step_handler(msg, _add_panel_step)


def _add_panel_step(message):
    if message.text and message.text.strip().lower() == "/cancel":
        bot.reply_to(message, "❌ Cancelled.")
        return
    uid = message.from_user.id
    text = ""
    if message.content_type == "text":
        text = message.text or ""
    elif message.content_type == "document":
        doc = message.document
        if not doc.file_name.endswith(".txt"):
            bot.reply_to(message, "❌ Sirf .txt file bhejo.")
            return
        try:
            info = bot.get_file(doc.file_id)
            content = bot.download_file(info.file_path)
            text = content.decode("utf-8", errors="ignore")
        except Exception as e:
            bot.reply_to(message, f"❌ File fail: {e}")
            return
    else:
        bot.reply_to(message, "❌ Text ya .txt file bhejo.")
        return
    found = extract_urls(text)
    if not found:
        bot.reply_to(message, "❌ Koi valid Firebase URL nahi mila.")
        return
    panels = load_user_panels(uid)
    added = 0
    for u in found:
        if u not in panels:
            panels.append(u)
            added += 1
    if added:
        save_user_panels(uid, panels)
    bot.reply_to(message,
        f"✅ <b>{added}</b> naye panels added.\n"
        f"📦 Your total: <b>{len(panels)}</b>")


@bot.callback_query_handler(func=lambda c: c.data == "btn_clean")
def cb_clean(call):
    bot.answer_callback_query(call.id, "🧹 Scanning...")
    uid = call.from_user.id
    threading.Thread(target=_run_clean_user, args=(call.message.chat.id, uid), daemon=True).start()


def _run_clean_user(chat_id, uid):
    panels = load_user_panels(uid)
    if not panels:
        bot.send_message(chat_id, "📭 Koi panel nahi.")
        return
    dead, alive = [], []
    for u in panels:
        r = probe_panel(u)
        if r["verdict"] == "OPEN":
            alive.append(u)
        else:
            dead.append((u, r["verdict"]))
    save_user_panels(uid, alive)
    lines = [f"🧹 <b>CLEAN COMPLETE</b>\n"]
    lines.append(f"🟢 Kept: <b>{len(alive)}</b>")
    lines.append(f"🗑 Removed: <b>{len(dead)}</b>")
    if dead:
        lines.append("\n<b>Removed:</b>")
        for u, v in dead[:20]:
            lines.append(f"  • <code>{short_name(u)}</code> — {v}")
    bot.send_message(chat_id, "\n".join(lines))


@bot.callback_query_handler(func=lambda c: c.data == "btn_stats")
def cb_stats(call):
    bot.answer_callback_query(call.id)
    uid = call.from_user.id
    panels = load_user_panels(uid)
    if not panels:
        bot.send_message(call.message.chat.id, "📭 Koi panel nahi.")
        return
    bot.send_message(call.message.chat.id, "📊 Stats nikaal raha hoon...")
    threading.Thread(target=_run_stats_user, args=(call.message.chat.id, uid, panels), daemon=True).start()


def _run_stats_user(chat_id, uid, panels):
    live = dead = locked = 0
    for u in panels:
        r = probe_panel(u)
        if r["verdict"] == "OPEN":
            live += 1
        elif r["verdict"] == "DEACTIVATED":
            dead += 1
        else:
            locked += 1
    text = (
        f"📊 <b>YOUR PANEL STATS</b>\n\n"
        f"📦 Total: <b>{len(panels)}</b>\n"
        f"🟢 Live: <b>{live}</b>\n"
        f"🔴 Deactivated: <b>{dead}</b>\n"
        f"🔒 Locked/Dead: <b>{locked}</b>\n")
    bot.send_message(chat_id, text)


@bot.callback_query_handler(func=lambda c: c.data == "btn_clear")
def cb_clear(call):
    bot.answer_callback_query(call.id)
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("💥 Clear My Panels", callback_data="clr_my_panels"),
        InlineKeyboardButton("📦 Clear My Dumps", callback_data="clr_my_dumps"),
        InlineKeyboardButton("❌ Cancel", callback_data="clr_cancel"),
    )
    bot.send_message(call.message.chat.id,
        "⚠️ <b>CLEAR MENU</b>\n\nKya clean karna hai?",
        reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("clr_"))
def cb_clear_action(call):
    uid = call.from_user.id
    action = call.data.replace("clr_", "")
    lines = []
    if action == "cancel":
        bot.answer_callback_query(call.id, "Cancelled")
        bot.edit_message_text("❌ Cancelled.",
                              call.message.chat.id, call.message.message_id)
        return
    if action == "my_panels":
        panels = load_user_panels(uid)
        count = len(panels)
        save_user_panels(uid, [])
        lines.append(f"🧹 Panels cleared: {count}")
    elif action == "my_dumps":
        d = user_dumps_dir(uid)
        if os.path.isdir(d):
            files = os.listdir(d)
            for f in files:
                try: os.remove(os.path.join(d, f))
                except: pass
            lines.append(f"📦 Dumps cleared: {len(files)}")
        else:
            lines.append("📦 No dumps")
    bot.answer_callback_query(call.id, "Done ✅")
    bot.edit_message_text(
        "✅ <b>CLEAR DONE</b>\n\n" + "\n".join(lines),
        call.message.chat.id, call.message.message_id)


# ============================================================
# 🔍 CHECK DEVICES BUTTON — MAIN FEATURE
# ============================================================
@bot.callback_query_handler(func=lambda c: c.data == "btn_check_devices")
def cb_check_devices(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id,
        "🔍 <b>CHECK DEVICES</b>\n\n"
        "Ek URL bhejo:\n"
        "• Website URL\n"
        "• Encoded URL (?s=... / ?m=...)\n"
        "• Direct Firebase URL\n\n"
        "Bot extract karke online devices check karega.\n\n"
        "<i>Cancel ke liye /cancel</i>")
    bot.register_next_step_handler(msg, _check_devices_step)


def _check_devices_step(message):
    if message.text and message.text.strip().lower() == "/cancel":
        bot.reply_to(message, "❌ Cancelled.")
        return
    if not message.text:
        bot.reply_to(message, "❌ URL bhejo.")
        return
    url = message.text.strip()
    if not url.startswith("http"):
        bot.reply_to(message, "❌ Valid URL bhejo.")
        return
    bot.reply_to(message, "🔍 Extract + check kar raha hoon...")
    threading.Thread(target=_run_check_devices, args=(message.chat.id, url), daemon=True).start()


def _run_check_devices(chat_id, url):
    t0 = time.time()

    # Step 1: extract Firebase URLs
    found = scan_url_for_firebase(url)
    if not found:
        bot.send_message(chat_id, "❌ Koi Firebase URL nahi mila.")
        return

    bot.send_message(chat_id,
        f"✅ <b>{len(found)} Firebase URL(s) mile</b>\n"
        f"📱 Ab devices check kar raha hoon...")

    # Step 2: check devices for each
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        device_results = list(ex.map(fetch_panel_devices, found))

    elapsed = time.time() - t0

    working = [r for r in device_results if r["path_used"]]
    total_online = sum(r["online"] for r in working)
    total_offline = sum(r["offline"] for r in working)
    total_unknown = sum(r["unknown"] for r in working)

    lines = []
    lines.append(f"🔍 <b>CHECK DEVICES COMPLETE</b>")
    lines.append(f"⏱ {elapsed:.1f}s  |  🌐 {len(found)} URLs")
    lines.append(f"✅ Working: <b>{len(working)}</b>  ❌ Dead: <b>{len(device_results)-len(working)}</b>")
    lines.append("")
    lines.append(f"🟢 Total Online: <b>{total_online}</b>")
    lines.append(f"🔴 Total Offline: <b>{total_offline}</b>")
    if total_unknown:
        lines.append(f"❓ Unknown: <b>{total_unknown}</b>")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📋 <b>PER PANEL:</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━")

    for r in sorted(working, key=lambda x: x["online"], reverse=True):
        lines.append("")
        lines.append(f"✅ <code>{r['short']}</code>")
        lines.append(f"   📡 {r['total']} devices | path: <code>{r['path_used']}</code>")
        lines.append(f"   🟢 Online: <b>{r['online']}</b>  🔴 Offline: <b>{r['offline']}</b>"
                     + (f"  ❓ {r['unknown']}" if r['unknown'] else ""))

    dead = [r for r in device_results if not r["path_used"]]
    if dead:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━")
        lines.append("❌ <b>NO DEVICE REGISTRY:</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━")
        for r in dead:
            lines.append(f"❌ <code>{r['short']}</code> — {r['error'] or r['status']}")

    out = "\n".join(lines)
    for chunk in [out[i:i+3800] for i in range(0, len(out), 3800)]:
        bot.send_message(chat_id, chunk, disable_web_page_preview=True)


# ============================================================
# TEXT COMMANDS (backup)
# ============================================================
@bot.message_handler(commands=['list'])
def cmd_list(message):
    track_user(message)
    panels = load_user_panels(message.from_user.id)
    if not panels:
        bot.reply_to(message, "📭 Koi panel nahi. ➕ Add Panel button tap kar.")
        return
    lines = [f"📋 <b>YOUR PANELS ({len(panels)})</b>\n"]
    for i, u in enumerate(panels, 1):
        lines.append(f"{i}. <code>{u}</code>")
    bot.send_message(message.chat.id, "\n".join(lines), disable_web_page_preview=True)


@bot.message_handler(commands=['addpanel'])
def cmd_addpanel(message):
    track_user(message)
    msg = bot.reply_to(message, "📥 Panel add karo (URLs ya .txt file):\n\n<i>Cancel ke liye /cancel</i>")
    bot.register_next_step_handler(msg, _add_panel_step)


@bot.message_handler(commands=['check'])
def cmd_check(message):
    track_user(message)
    uid = message.from_user.id
    panels = load_user_panels(uid)
    if not panels:
        bot.reply_to(message, "📭 Koi panel nahi.")
        return
    bot.reply_to(message, f"⏳ {len(panels)} panels check kar raha hoon...")
    threading.Thread(target=_run_check_user, args=(message.chat.id, panels), daemon=True).start()


def _run_check_user(chat_id, panels):
    results = [probe_panel(u) for u in panels]
    live = [r for r in results if r["verdict"] == "OPEN"]
    dead = [r for r in results if r["verdict"] != "OPEN"]
    lines = [f"📊 <b>CHECK RESULTS — {datetime.now():%H:%M:%S}</b>\n"]
    lines.append(f"🟢 Live: <b>{len(live)}</b>   🔴 Dead: <b>{len(dead)}</b>\n")
    if live:
        lines.append("🟢 <b>LIVE:</b>")
        for r in live:
            lines.append(f"  • <code>{r['short']}</code> — {r['count']} keys")
    if dead:
        lines.append("\n🔴 <b>DEAD:</b>")
        for r in dead:
            lines.append(f"  • <code>{r['short']}</code> — {r['verdict']}")
    out = "\n".join(lines)
    for chunk in [out[i:i+3800] for i in range(0, len(out), 3800)]:
        bot.send_message(chat_id, chunk, disable_web_page_preview=True)


@bot.message_handler(commands=['devices'])
def cmd_devices(message):
    track_user(message)
    uid = message.from_user.id
    panels = load_user_panels(uid)
    if not panels:
        bot.reply_to(message, "📭 Koi panel nahi.")
        return
    bot.reply_to(message, f"📱 {len(panels)} panels ka device check...")
    threading.Thread(target=_run_devices_user, args=(message.chat.id, panels), daemon=True).start()


def _run_devices_user(chat_id, panels):
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(fetch_panel_devices, panels))
    elapsed = time.time() - t0
    working = [r for r in results if r["path_used"]]
    total_online = sum(r["online"] for r in working)
    total_offline = sum(r["offline"] for r in working)
    total_unknown = sum(r["unknown"] for r in working)
    lines = []
    lines.append(f"📱 <b>DEVICE CHECK COMPLETE</b>")
    lines.append(f"⏱ {elapsed:.1f}s  |  📦 {len(results)}")
    lines.append(f"✅ Working: <b>{len(working)}</b>")
    lines.append("")
    lines.append(f"🟢 Online: <b>{total_online}</b>")
    lines.append(f"🔴 Offline: <b>{total_offline}</b>")
    if total_unknown:
        lines.append(f"❓ Unknown: <b>{total_unknown}</b>")
    for r in sorted(working, key=lambda x: x["online"], reverse=True):
        lines.append("")
        lines.append(f"✅ <code>{r['short']}</code>")
        lines.append(f"   📡 {r['total']} | path: <code>{r['path_used']}</code>")
        lines.append(f"   🟢 {r['online']}  🔴 {r['offline']}"
                     + (f"  ❓ {r['unknown']}" if r['unknown'] else ""))
    out = "\n".join(lines)
    for chunk in [out[i:i+3800] for i in range(0, len(out), 3800)]:
        bot.send_message(chat_id, chunk, disable_web_page_preview=True)


# ============================================================
# 👑 ADMIN COMMANDS
# ============================================================
@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "🔒 Sirf admin ke liye.")
        return
    all_u = all_users_with_panels()
    total_panels = sum(len(p) for p in all_u.values())
    text = (
        "👑 <b>ADMIN PANEL</b>\n\n"
        "📋 <b>Commands:</b>\n"
        "/admin_stats — system stats\n"
        "/admin_users — sab users + unke panels\n"
        "/admin_wipe_all — SAB KUCH delete\n"
        "/admin_backup — poora backup\n"
        "/admin_broadcast — message bhejo\n\n"
        f"👥 Total users: <b>{len(USERS)}</b>\n"
        f"👥 Users with panels: <b>{len(all_u)}</b>\n"
        f"📦 Total panels (all users): <b>{total_panels}</b>"
    )
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=['admin_stats'])
def cmd_admin_stats(message):
    if not is_admin(message.from_user.id): return
    all_u = all_users_with_panels()
    total_panels = sum(len(p) for p in all_u.values())
    text = (
        f"📊 <b>SYSTEM STATS</b>\n\n"
        f"👥 Total users: <b>{len(USERS)}</b>\n"
        f"👥 Active (with panels): <b>{len(all_u)}</b>\n"
        f"📦 Total panels: <b>{total_panels}</b>\n"
        f"🕐 {datetime.now():%Y-%m-%d %H:%M:%S}"
    )
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=['admin_users'])
def cmd_admin_users(message):
    if not is_admin(message.from_user.id): return
    all_u = all_users_with_panels()
    if not all_u:
        bot.reply_to(message, "👥 Koi user nahi.")
        return
    lines = [f"👥 <b>USERS WITH PANELS: {len(all_u)}</b>\n"]
    for uid, panels in all_u.items():
        info = USERS.get(uid, {})
        name = info.get("name", "?")
        uname = info.get("username", "")
        uname_str = f"@{uname}" if uname else ""
        lines.append(f"• <code>{uid}</code> — {name} {uname_str}")
        lines.append(f"  📦 {len(panels)} panels")
    out = "\n".join(lines)
    for chunk in [out[i:i+3800] for i in range(0, len(out), 3800)]:
        bot.send_message(message.chat.id, chunk, disable_web_page_preview=True)


@bot.message_handler(commands=['admin_wipe_all'])
def cmd_admin_wipe_all(message):
    if not is_admin(message.from_user.id): return
    import shutil
    total = 0
    if os.path.isdir(BASE_DIR):
        for uid in os.listdir(BASE_DIR):
            d = os.path.join(BASE_DIR, uid)
            if os.path.isdir(d):
                try:
                    shutil.rmtree(d)
                    total += 1
                except: pass
    bot.reply_to(message, f"💥 <b>ALL WIPED</b>\n{total} users ka data delete.")


@bot.message_handler(commands=['admin_backup'])
def cmd_admin_backup(message):
    if not is_admin(message.from_user.id): return
    import shutil
    if os.path.isdir(BASE_DIR):
        shutil.make_archive("backup_all", "zip", BASE_DIR)
        with open("backup_all.zip", "rb") as f:
            bot.send_document(message.chat.id, f, caption="💾 Full backup")
    else:
        bot.reply_to(message, "❌ Koi data nahi.")


@bot.message_handler(commands=['admin_broadcast'])
def cmd_admin_broadcast(message):
    if not is_admin(message.from_user.id): return
    bot.reply_to(message, "📢 Message bhejo (sab users ko jayega):")
    bot.register_next_step_handler(message, _broadcast_send)


def _broadcast_send(message):
    if not is_admin(message.from_user.id): return
    if not message.text:
        bot.reply_to(message, "❌ Text bhejo.")
        return
    sent = 0
    for uid in USERS.keys():
        try:
            bot.send_message(int(uid), f"📢 <b>BROADCAST</b>\n\n{message.text}")
            sent += 1
        except: pass
    bot.reply_to(message, f"✅ Sent: {sent}")


@bot.message_handler(commands=['admin_restart'])
def cmd_admin_restart(message):
    if not is_admin(message.from_user.id): return
    bot.reply_to(message, "🔄 Restarting...")
    time.sleep(1)
    os._exit(0)


# ============================================================
# RUNNER
# ============================================================
if __name__ == "__main__":
    print("🚀 Ujala Auto Bot starting...")
    print(f"👥 Users tracked: {len(USERS)}")
    print(f"👑 Admins: {ALLOWED_IDS}")
    os.makedirs(BASE_DIR, exist_ok=True)
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=15)
        except Exception as e:
            print(f"⚠️ Polling error: {e}")
            time.sleep(3)
            print("🔄 Restarting...")
