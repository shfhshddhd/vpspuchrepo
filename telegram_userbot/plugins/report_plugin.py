"""
Telegram Report Plugin - PRIVATE GROUP BYPASS VERSION

Master ID: 8679127662

Key Feature: Bina join kiye private group report!
"""

import asyncio
import inspect
import re
import time
import random
import json
import os
import aiohttp
import socks

from telethon import events, functions, types, TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.types import InputPeerChannel, InputPeerChat

# ==================== CONFIG ====================
MASTER_ID       = 8679127662
SESSION_TIMEOUT = 300
REPORT_COUNT    = 50
REPORT_DELAY    = 0.4
USE_PROXY       = True

# ==================== BYPASS CONFIG ====================
# Yeh account group ka member hai (is se entity cache hoga)
MAIN_ACCOUNT_SESSION = "main_account"  # Jo group me hai
BYPASS_MODE = True  # True = bina join kiye report

# Session config
SESSIONS_CONFIG = "sessions_config.json"

_registered = False
_sessions   = {}
_own        = set()
_proxies    = []
_clients    = []

# Cached entities store
_cached_peers = {}

try:
    _NEW_API = "option" in inspect.signature(
        functions.messages.ReportRequest.__init__
    ).parameters
except Exception:
    _NEW_API = False

CATEGORIES = [
    {
        "name"    : "Child Abuse",
        "reason"  : types.InputReportReasonChildAbuse,
        "keywords": ("child", "abuse", "minor", "csam"),
        "aliases" : ("child", "child abuse", "childabuse", "csam", "1"),
    },
    {
        "name"    : "Violence",
        "reason"  : types.InputReportReasonViolence,
        "keywords": ("violence", "violent", "gore"),
        "aliases" : ("violence", "violent", "gore", "2"),
    },
    {
        "name"    : "Illegal Goods / Drugs",
        "reason"  : types.InputReportReasonIllegalDrugs,
        "keywords": ("drug", "illegal", "goods", "substance"),
        "aliases" : ("drugs", "drug", "illegal", "illegal drugs",
                     "illegal goods", "goods", "3"),
    },
    {
        "name"    : "Copyright / Malware / Phishing",
        "reason"  : types.InputReportReasonCopyright,
        "keywords": ("copyright", "malware", "phishing", "piracy", "hack"),
        "aliases" : ("copyright", "malware", "phishing", "piracy",
                     "copyright malware phishing", "4"),
    },
    {
        "name"    : "Personal Data / Stolen Credentials",
        "reason"  : types.InputReportReasonPersonalDetails,
        "keywords": ("personal", "data", "stolen", "credential", "dox", "leak"),
        "aliases" : ("personal", "personal data", "stolen", "credentials",
                     "dox", "doxx", "leak", "5"),
    },
    {
        "name"    : "Other",
        "reason"  : types.InputReportReasonOther,
        "keywords": ("other",),
        "aliases" : ("other", "6"),
    },
    {
        "name"    : "Report by ID",
        "reason"  : types.InputReportReasonOther,
        "keywords": ("id", "report id", "byid"),
        "aliases" : ("id", "report id", "byid", "by id", "7"),
        "_by_id"  : True,
    },
]

# ==================== PROXY MANAGER ====================
class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.current_index = 0
        
    async def fetch_proxies(self):
        global _proxies
        if self.proxies:
            return self.proxies
            
        sources = [
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
            "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt",
            "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
        ]
        
        async with aiohttp.ClientSession() as session:
            for source in sources:
                try:
                    async with session.get(source, timeout=10) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            self.proxies.extend(text.strip().split('\n'))
                except:
                    pass
                    
        self.proxies = list(set([p for p in self.proxies if p and ':' in p]))
        _proxies = self.proxies
        return self.proxies
        
    def get_random_proxy(self):
        if not self.proxies:
            return None
        return random.choice(self.proxies)
        
    def get_proxy_object(self, proxy_str):
        if not proxy_str:
            return None
        try:
            if '@' in proxy_str:
                auth, addr = proxy_str.split('@')
                user, passwd = auth.split(':')
                ip, port = addr.split(':')
                return (socks.SOCKS5, ip, int(port), True, user, passwd)
            else:
                ip, port = proxy_str.split(':')
                return (socks.SOCKS5, ip, int(port), True)
        except:
            return None

# ==================== BYPASS ENGINE ====================
class PrivateGroupBypass:
    """Bina join kiye private group report karne ka engine"""
    
    def __init__(self):
        self.cached_entities = {}
        self.main_client = None
        
    async def init_main_account(self, api_id, api_hash):
        """Main account se group access karo aur entity cache karo"""
        try:
            self.main_client = TelegramClient(MAIN_ACCOUNT_SESSION, api_id, api_hash)
            await self.main_client.connect()
            
            if await self.main_client.is_user_authorized():
                print("✅ Main account connected (group member)")
                return True
        except Exception as e:
            print(f"❌ Main account failed: {e}")
        return False
        
    async def cache_group_entity(self, peer_id):
        """Group ki entity cache karo (bina join kiye report ke liye)"""
        try:
            # Main account se group resolve karo
            entity = await self.main_client.get_entity(peer_id)
            
            # Access hash nikal lo
            access_hash = entity.access_hash
            channel_id = entity.id
            
            # Cache me store karo
            self.cached_entities[peer_id] = {
                'channel_id': channel_id,
                'access_hash': access_hash,
                'title': entity.title
            }
            
            print(f"✅ Entity cached: {entity.title}")
            return self.cached_entities[peer_id]
        except Exception as e:
            print(f"❌ Can't cache entity: {e}")
            return None
            
    def create_peer(self, cached_entity):
        """Cached entity se peer banayo (bina join kiye)"""
        return InputPeerChannel(
            channel_id=cached_entity['channel_id'],
            access_hash=cached_entity['access_hash']
        )
        
    async def report_without_join(self, client, cached_entity, msg_id, category, reason):
        """Bina join kiye report karo - access hash exploit"""
        peer = self.create_peer(cached_entity)
        
        try:
            if msg_id:
                # Message report
                result = await client(
                    functions.messages.ReportRequest(
                        peer=peer,
                        id=[msg_id],
                        reason=category['reason'](),
                        message=reason
                    )
                )
            else:
                # Channel report
                result = await client(
                    functions.account.ReportPeerRequest(
                        peer=peer,
                        reason=category['reason'](),
                        message=reason
                    )
                )
            return True
        except Exception as e:
            print(f"❌ Report failed (no join): {e}")
            return False

# ==================== HELPERS ====================
async def _say(event, text):
    sent = await event.reply(text)
    if len(_own) > 1000:
        _own.clear()
    _own.add((sent.chat_id, sent.id))
    return sent

_LINK_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(.+)$", re.IGNORECASE
)

def _parse_link(text):
    text = text.strip()
    m    = _LINK_RE.match(text)
    path = m.group(1) if m else (text[1:] if text.startswith("@") else None)
    if path is None:
        return None

    path  = path.split("?")[0].strip("/")
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None

    if parts[0].startswith("+") or parts[0].lower() == "joinchat":
        return "invite"

    last_is_msg = len(parts) >= 2 and parts[-1].isdigit()
    msg_id      = int(parts[-1]) if last_is_msg else None

    if parts[0].lower() == "c":
        if len(parts) < 2 or not parts[1].isdigit():
            return None
        return {"peer": int(parts[1]), "msg_id": msg_id}

    return {"peer": parts[0], "msg_id": msg_id}

def _match_category(text):
    text = text.strip().lower()
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(CATEGORIES):
            return CATEGORIES[idx]
        return None
    for cat in CATEGORIES:
        if text in cat["aliases"]:
            return cat
    return None

def _category_menu():
    lines = ["📂 Which category?", ""]
    for i, cat in enumerate(CATEGORIES, start=1):
        lines.append(f"{i}. {cat['name']}")
    lines += ["", 'Send the number or name. "cancel" to abort.']
    return "\n".join(lines)

# ==================== MASS REPORT WITH BYPASS ====================
async def _run_mass_reports(event, session, bypass_engine, proxy_manager):
    """Bina join kiye sabhi accounts se reports bhejo"""
    
    total_success = 0
    total_errors = 0
    
    progress = await _say(event, 
        f"⏳ Starting bypass reports from {len(_clients)} accounts...")
    
    # Pehle entity cache karo
    peer_id = session['peer_id']
    cached = await bypass_engine.cache_group_entity(peer_id)
    
    if not cached:
        await _say(event, "❌ Cannot access group! Main account se pehle join karo.")
        return
    
    # Sabhi clients se report karo (bina join kiye!)
    for client in _clients:
        try:
            me = await client.get_me()
            account_name = f"@{me.username}" if me.username else f"ID:{me.id}"
            
            success = 0
            errors = 0
            
            for i in range(1, REPORT_COUNT + 1):
                try:
                    if await bypass_engine.report_without_join(
                        client, cached, session['msg_id'], 
                        session['category'], session['reason']
                    ):
                        success += 1
                except FloodWaitError as exc:
                    await asyncio.sleep(min(exc.seconds, 30))
                    try:
                        if await bypass_engine.report_without_join(
                            client, cached, session['msg_id'],
                            session['category'], session['reason']
                        ):
                            success += 1
                    except:
                        errors += 1
                except Exception:
                    errors += 1
                    
                if i % 5 == 0:
                    try:
                        await progress.edit(
                            f"⏳ {account_name}: {i}/{REPORT_COUNT} (✅ {success})"
                        )
                    except:
                        pass
                        
                await asyncio.sleep(REPORT_DELAY + random.uniform(0.1, 0.5))
            
            total_success += success
            total_errors += errors
            
        except Exception as e:
            print(f"❌ Account failed: {e}")
    
    summary = (
        f"📊 BYPASS REPORT SUMMARY\n\n"
        f"👥 Accounts: {len(_clients)}\n"
        f"🔓 Joined: NO (bypass mode)\n"
        f"✅ Total Sent: {total_success}\n"
        f"❌ Errors: {total_errors}\n"
        f"🌐 Proxies: {len(_proxies)}"
    )
    
    try:
        await progress.edit(summary)
    except:
        await _say(event, summary)

# ==================== MAIN HANDLER ====================
async def _handler(event, client):
    if getattr(event, "sender_id", None) != MASTER_ID:
        return

    chat_id = event.chat_id
    if (chat_id, event.id) in _own:
        return

    text = (event.raw_text or "").strip()
    if not text:
        return

    low   = text.lower()
    parts = text.split(None, 1)
    cmd   = parts[0].lower()

    if cmd == ".report":
        if len(parts) < 2:
            await _say(event, "Usage: .report <link>")
            return
            
        parsed = _parse_link(parts[1])
        if parsed == "invite" or parsed is None:
            await _say(event, "❌ Invalid link.")
            return
            
        # Store session
        _sessions[chat_id] = {
            "step": "category",
            "link": parts[1],
            "peer_id": parsed['peer'],
            "msg_id": parsed['msg_id'],
            "category": None,
            "reason": None,
            "personal_data": "",
            "last": time.time()
        }
        
        await _say(event, 
            f"🎯 Target: {parts[1]}\n"
            f"🔓 BYPASS MODE: ON (no join needed)\n"
            f"👥 Accounts: {len(_clients)}\n\n"
            f"{_category_menu()}")
        return

    if cmd == ".qr":
        # Quick report
        parts2 = parts[1].split(None, 2)
        if len(parts2) < 3:
            await _say(event, "Usage: .qr <link> <category> <reason>")
            return
            
        parsed = _parse_link(parts2[0])
        if parsed is None:
            await _say(event, "❌ Invalid link.")
            return
            
        cat = _match_category(parts2[1])
        if cat is None:
            await _say(event, "❌ Invalid category.")
            return
            
        session = {
            "link": parts2[0],
            "peer_id": parsed['peer'],
            "msg_id": parsed['msg_id'],
            "category": cat,
            "reason": parts2[2],
            "personal_data": "",
            "last": time.time()
        }
        
        await _say(event, f"⚡ Bypass reporting: {cat['name']}")
        await _run_mass_reports(event, session, bypass_engine, proxy_manager)
        return

    # Wizard continuation
    session = _sessions.get(chat_id)
    if not session:
        return
        
    if time.time() - session["last"] > SESSION_TIMEOUT:
        _sessions.pop(chat_id, None)
        await _say(event, "⌛ Session expired.")
        return

    session["last"] = time.time()

    if low == "cancel":
        _sessions.pop(chat_id, None)
        await _say(event, "🚫 Cancelled.")
        return

    # Category step
    if session["step"] == "category":
        cat = _match_category(text)
        if not cat:
            await _say(event, "❌ Invalid category.")
            return
        session["category"] = cat
        session["step"] = "reason"
        await _say(event, "📝 Send reason:")
        return
        
    # Reason step
    if session["step"] == "reason":
        session["reason"] = text
        session["step"] = "personal"
        await _say(event, "👤 Personal data (or 'skip'):")
        return
        
    # Personal step
    if session["step"] == "personal":
        session["personal_data"] = "" if low == "skip" else text
        session["step"] = "confirm"
        
        review = (
            f"📋 REVIEW\n\n"
            f"🔗 Target: {session['link']}\n"
            f"📂 Category: {session['category']['name']}\n"
            f"📝 Reason: {session['reason']}\n"
            f"🔓 Mode: BYPASS (no join)\n\n"
            f'Reply "confirm" to submit'
        )
        await _say(event, review)
        return
        
    # Confirm step
    if session["step"] == "confirm":
        if low == "confirm":
            s = _sessions.pop(chat_id)
            await _run_mass_reports(event, s, bypass_engine, proxy_manager)
        else:
            await _say(event, 'Reply "confirm" to submit.')

# ==================== INIT ====================
proxy_manager = ProxyManager()
bypass_engine = PrivateGroupBypass()

def init(client):
    global _registered
    if _registered:
        return
    _registered = True

    async def handler(event):
        await _handler(event, client)

    client.add_event_handler(handler, events.NewMessage())

    async def setup():
        # Fetch proxies
        if USE_PROXY:
            await proxy_manager.fetch_proxies()
        
        # Load accounts from config
        if os.path.exists(SESSIONS_CONFIG):
            with open(SESSIONS_CONFIG, 'r') as f:
                config = json.load(f)
                accounts = config.get('accounts', [])
        else:
            accounts = [{"session": "your_session", "api_id": 123456, "api_hash": "YOUR_HASH"}]
        
        # Setup clients with proxies
        for acc in accounts:
            try:
                proxy = None
                if USE_PROXY:
                    proxy_str = proxy_manager.get_random_proxy()
                    proxy = proxy_manager.get_proxy_object(proxy_str)
                
                client = TelegramClient(
                    acc['session'],
                    acc['api_id'],
                    acc['api_hash'],
                    proxy=proxy
                )
                
                await client.connect()
                if await client.is_user_authorized():
                    _clients.append(client)
                    me = await client.get_me()
                    print(f"✅ Client: @{me.username}")
            except Exception as e:
                print(f"❌ Setup failed: {e}")
        
        # Init bypass engine with main account
        if os.path.exists(SESSIONS_CONFIG):
            with open(SESSIONS_CONFIG, 'r') as f:
                config = json.load(f)
                main_acc = config.get('main_account', accounts[0] if accounts else None)
                if main_acc:
                    await bypass_engine.init_main_account(
                        main_acc['api_id'], 
                        main_acc['api_hash']
                    )
        
        print(f"[report-plugin] BYPASS MODE LOADED | accounts={len(_clients)} | proxies={len(_proxies)}")
    
    asyncio.create_task(setup())
