"""
Telegram Report Plugin (Telethon userbot)

Master ID: 8732266416

Commands:
    .report <link>
        .report t.me/channelname
        .report t.me/channelname/123
        .report t.me/c/1234567890/123
        .report id <peer> <msg_id>     ← report by raw message ID

    .qr <link> <cat> <reason>          ← quick report, no wizard
        .qr t.me/channel/12 1 This is spam
        .qr t.me/channel 4 phishing malware
        (cat = number 1-7 or category name)

Wizard flow (.report):
    1. Category  → send number (1-7) or name
    2. Reason    → send reason text
    3. Personal  → send personal data or "skip"
    4. Review    → send "confirm" to submit or "cancel" to abort

Reports 50x per command from your account.
"""

import asyncio
import inspect
import re
import time

from telethon import events, functions, types
from telethon.errors import FloodWaitError, RPCError


MASTER_ID       = 8732266416
SESSION_TIMEOUT = 300
REPORT_COUNT    = 50
REPORT_DELAY    = 0.4

_registered = False
_sessions   = {}
_own        = set()

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


# ─── helpers ──────────────────────────────────────────────────────────────────

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
        return {"peer": types.PeerChannel(int(parts[1])), "msg_id": msg_id}

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


def _review_card(session):
    return (
        "📋 REPORT REVIEW\n\n"
        f"🔗 Target      : {session['link']}\n"
        f"📂 Category    : {session['category']['name']}\n"
        f"📝 Reason      : {session['reason']}\n"
        f"👤 Personal    : {session['personal_data'] or '(none)'}\n"
        f"🔁 Count       : {REPORT_COUNT} reports\n\n"
        'Reply "confirm" to submit all\n'
        'Reply "cancel"  to abort'
    )


def _build_message(reason, personal_data, index):
    base = reason
    if personal_data:
        base += (
            f"\n\n--- Personal identification ---\n"
            f"{personal_data}\n"
            f"--- Report #{index}/{REPORT_COUNT} ---"
        )
    else:
        base += f"\n\n--- Report #{index}/{REPORT_COUNT} ---"
    return base[:512]


def _pick_option(options, category):
    for opt in options:
        t = (opt.text or "").lower()
        if any(k in t for k in category["keywords"]):
            return opt
    for opt in options:
        if "other" in (opt.text or "").lower():
            return opt
    return options[0]


# ─── core submit ──────────────────────────────────────────────────────────────

async def _submit_once(client, session, index):
    peer     = session["input_peer"]
    msg_id   = session["msg_id"]
    category = session["category"]
    message  = _build_message(session["reason"], session["personal_data"], index)

    # peer-level report (no message id)
    if msg_id is None:
        await client(
            functions.account.ReportPeerRequest(
                peer    = peer,
                reason  = category["reason"](),
                message = message,
            )
        )
        return True

    # message-level, old API
    if not _NEW_API:
        await client(
            functions.messages.ReportRequest(
                peer    = peer,
                id      = [msg_id],
                reason  = category["reason"](),
                message = message,
            )
        )
        return True

    # message-level, new option-flow API
    option = session.get("_custom_option", b"")

    for _ in range(8):
        result = await client(
            functions.messages.ReportRequest(
                peer    = peer,
                id      = [msg_id],
                option  = option,
                message = message,
            )
        )
        kind = type(result).__name__

        if kind == "ReportResultReported":
            return True
        if kind == "ReportResultAddComment":
            option = result.option
            continue
        if kind == "ReportResultChooseOption":
            option = _pick_option(result.options, category).option
            continue
        return False

    return False


async def _run_reports(client, event, session):
    success     = 0
    flood_waits = 0
    errors      = []

    progress = await _say(event, f"⏳ Sending reports… 0/{REPORT_COUNT}")

    for i in range(1, REPORT_COUNT + 1):
        try:
            if await _submit_once(client, session, i):
                success += 1
        except FloodWaitError as exc:
            flood_waits += 1
            await asyncio.sleep(min(exc.seconds, 30))
            try:
                if await _submit_once(client, session, i):
                    success += 1
            except Exception as e2:
                errors.append(f"#{i}: {type(e2).__name__}")
        except RPCError as exc:
            errors.append(f"#{i}: {type(exc).__name__}")
        except Exception as exc:
            errors.append(f"#{i}: {type(exc).__name__}: {exc}")

        if i % 5 == 0 or i == REPORT_COUNT:
            try:
                await progress.edit(
                    f"⏳ Sending… {i}/{REPORT_COUNT} (✅ {success})"
                )
            except Exception:
                pass

        if i < REPORT_COUNT:
            await asyncio.sleep(REPORT_DELAY)

    lines = [
        "📊 REPORT SUMMARY", "",
        f"✅ Sent       : {success}/{REPORT_COUNT}",
        f"🌊 FloodWaits : {flood_waits}",
    ]
    if errors:
        lines += [f"❌ Errors     : {len(errors)}"] + errors[:10]

    try:
        await progress.edit("\n".join(lines))
    except Exception:
        await _say(event, "\n".join(lines))


# ─── resolve peer helper ──────────────────────────────────────────────────────

async def _resolve(client, event, parsed):
    try:
        input_peer = await client.get_input_entity(parsed["peer"])
        entity     = await client.get_entity(input_peer)
    except Exception as exc:
        await _say(event, f"❌ Couldn't find that chat: {type(exc).__name__}")
        return None, None

    msg_id = parsed["msg_id"]
    if msg_id is not None:
        try:
            msg = await client.get_messages(input_peer, ids=msg_id)
        except Exception:
            msg = None
        if not msg:
            await _say(event, "❌ Message not found.")
            return None, None

    return input_peer, entity


# ─── .report wizard ───────────────────────────────────────────────────────────

async def _start_wizard(client, event, arg):
    # .report id <peer> <msg_id>  — raw ID mode
    id_m = re.match(r"^id\s+(\S+)\s+(\d+)$", arg, re.IGNORECASE)
    if id_m:
        parsed = {"peer": id_m.group(1), "msg_id": int(id_m.group(2))}
    else:
        parsed = _parse_link(arg)
        if parsed == "invite":
            await _say(event,
                "❌ Invite links can't be reported directly. "
                "Use a public or message link.")
            return
        if parsed is None:
            await _say(event,
                "❌ Couldn't parse that link.\n\n"
                "Examples:\n"
                "  .report t.me/channel\n"
                "  .report t.me/channel/123\n"
                "  .report id username 456")
            return

    input_peer, entity = await _resolve(client, event, parsed)
    if input_peer is None:
        return

    title = (
        getattr(entity, "title", None)
        or getattr(entity, "username", None)
        or getattr(entity, "first_name", None)
        or "unknown"
    )

    _sessions[event.chat_id] = {
        "step"         : "category",
        "link"         : arg.strip(),
        "input_peer"   : input_peer,
        "msg_id"       : parsed["msg_id"],
        "category"     : None,
        "reason"       : None,
        "personal_data": "",
        "last"         : time.time(),
    }

    what = "message" if parsed["msg_id"] else "chat"
    await _say(event,
        f"🎯 Target {what}: {title}\n"
        f"🔁 Will send {REPORT_COUNT} reports.\n\n"
        f"{_category_menu()}")


# ─── .qr quick-report ─────────────────────────────────────────────────────────

async def _quick_report(client, event, arg):
    parts = arg.split(None, 2)

    # .qr id <peer> <msgid> <cat> <reason>
    if parts and parts[0].lower() == "id":
        parts2 = arg.split(None, 4)
        if len(parts2) < 5:
            await _say(event,
                "Usage: .qr id <peer> <msg_id> <category> <reason>")
            return
        _, raw_peer, raw_mid, cat_arg, reason = parts2
        parsed = {"peer": raw_peer, "msg_id": int(raw_mid)}
    else:
        if len(parts) < 3:
            await _say(event,
                "Usage: .qr <link> <category> <reason>\n"
                "Example: .qr t.me/channel/12 4 phishing malware")
            return
        link_arg, cat_arg, reason = parts
        parsed = _parse_link(link_arg)
        if parsed == "invite" or parsed is None:
            await _say(event, "❌ Invalid link.")
            return

    cat = _match_category(cat_arg)
    if cat is None:
        await _say(event,
            f"❌ Unknown category: {cat_arg!r}\n\n"
            + _category_menu())
        return

    input_peer, entity = await _resolve(client, event, parsed)
    if input_peer is None:
        return

    title = (
        getattr(entity, "title", None)
        or getattr(entity, "username", None)
        or getattr(entity, "first_name", None)
        or "unknown"
    )

    session = {
        "link"         : arg.split()[0],
        "input_peer"   : input_peer,
        "msg_id"       : parsed["msg_id"],
        "category"     : cat,
        "reason"       : reason,
        "personal_data": "",
        "last"         : time.time(),
    }

    what = "message" if parsed["msg_id"] else "chat"
    await _say(event,
        f"⚡ Quick-reporting {what}: {title}\n"
        f"📂 {cat['name']}  |  🔁 {REPORT_COUNT} reports firing…")

    await _run_reports(client, event, session)


# ─── wizard step handler ──────────────────────────────────────────────────────

async def _wizard_step(client, event, session, text):
    low = text.lower().strip()

    if session["step"] == "category":
        cat = _match_category(text)
        if not cat:
            await _say(event, "❌ Invalid category.\n\n" + _category_menu())
            return
        session["category"] = cat
        session["step"]     = "reason"
        if cat.get("_by_id"):
            await _say(event,
                f"✅ Category: {cat['name']}\n\n"
                "📝 Send the report reason text.\n"
                "Optionally prefix with a hex option byte: `0x01 reason text`")
        else:
            await _say(event,
                f"✅ Category: {cat['name']}\n\n"
                "📝 Send the reason text.")
        return

    if session["step"] == "reason":
        if session["category"].get("_by_id"):
            m = re.match(r"^(0x[0-9a-f]{1,4})\s+(.*)", text, re.IGNORECASE)
            if m:
                session["_custom_option"] = bytes.fromhex(m.group(1)[2:].zfill(2))
                text = m.group(2)
        session["reason"] = text
        session["step"]   = "personal_data"
        await _say(event,
            "✅ Reason saved.\n\n"
            "👤 Send personal data to embed (name, phone, address, ID…)\n"
            'or "skip" to leave empty.')
        return

    if session["step"] == "personal_data":
        session["personal_data"] = "" if low == "skip" else text
        session["step"]          = "confirm"
        await _say(event, _review_card(session))
        return

    if session["step"] == "confirm":
        if low != "confirm":
            await _say(event, 'Reply "confirm" to submit or "cancel" to abort.')
            return
        s = _sessions.pop(event.chat_id)
        await _run_reports(client, event, s)


# ─── main handler ─────────────────────────────────────────────────────────────

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

    # .report
    if cmd == ".report":
        if len(parts) < 2:
            await _say(event,
                "Usage:\n"
                "  .report <link>\n"
                "  .report t.me/channel\n"
                "  .report t.me/channel/123\n"
                "  .report id <peer> <msg_id>")
            return
        _sessions.pop(chat_id, None)
        await _start_wizard(client, event, parts[1])
        return

    # .qr
    if cmd == ".qr":
        if len(parts) < 2:
            await _say(event,
                "Usage: .qr <link> <category> <reason>\n"
                "       .qr id <peer> <msg_id> <category> <reason>\n\n"
                + _category_menu())
            return
        await _quick_report(client, event, parts[1])
        return

    # wizard continuation
    session = _sessions.get(chat_id)
    if not session:
        return

    if time.time() - session["last"] > SESSION_TIMEOUT:
        _sessions.pop(chat_id, None)
        await _say(event, "⌛ Session expired. Use .report <link> again.")
        return

    session["last"] = time.time()

    if low == "cancel":
        _sessions.pop(chat_id, None)
        await _say(event, "🚫 Report cancelled.")
        return

    await _wizard_step(client, event, session, text)


# ─── init ─────────────────────────────────────────────────────────────────────

def init(client):
    global _registered
    if _registered:
        return
    _registered = True

    async def handler(event):
        await _handler(event, client)

    client.add_event_handler(handler, events.NewMessage())

    print(
        "[report-plugin] Loaded | "
        f"master={MASTER_ID} | "
        f"count={REPORT_COUNT} | "
        f"categories={len(CATEGORIES)} | "
        f"api={'option-flow' if _NEW_API else 'reason-flow'}"
    )
