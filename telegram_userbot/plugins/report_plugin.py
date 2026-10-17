"""Single-submission Telegram content reporting plugin for hosted userbots.

Use .report <Telegram link>, choose the most accurate category, enter a
truthful reason, and confirm once. This plugin intentionally submits one report.
"""

import inspect
import re
import time

from telethon import events, functions, types
from plugins.bot import add_handler

SESSION_TIMEOUT = 300
_sessions = {}
_own_messages = set()
_client = None

try:
    _NEW_API = "option" in inspect.signature(
        functions.messages.ReportRequest.__init__
    ).parameters
except Exception:
    _NEW_API = False

CATEGORIES = [
    ("Spam", types.InputReportReasonSpam, ("spam", "scam", "unsolicited")),
    ("Violence", types.InputReportReasonViolence, ("violence", "violent", "gore")),
    ("Child abuse", types.InputReportReasonChildAbuse, ("child", "minor", "abuse")),
    ("Illegal goods / drugs", types.InputReportReasonIllegalDrugs, ("drugs", "illegal")),
    ("Personal data", types.InputReportReasonPersonalDetails, ("personal", "dox", "privacy")),
    ("Copyright", types.InputReportReasonCopyright, ("copyright", "piracy")),
    ("Other", types.InputReportReasonOther, ("other",)),
]

_LINK_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(.+)$", re.IGNORECASE
)


async def _say(event, text):
    sent = await event.reply(text)
    _own_messages.add((sent.chat_id, sent.id))
    if len(_own_messages) > 1000:
        _own_messages.clear()
    return sent


def _parse_link(text):
    match = _LINK_RE.match(text.strip())
    if not match:
        return None
    parts = [part for part in match.group(1).split("?")[0].strip("/").split("/") if part]
    if not parts or parts[0].startswith("+") or parts[0].lower() == "joinchat":
        return None

    msg_id = int(parts[-1]) if len(parts) > 1 and parts[-1].isdigit() else None
    if parts[0].lower() == "c":
        if len(parts) < 2 or not parts[1].isdigit():
            return None
        return {"peer": types.PeerChannel(int(parts[1])), "msg_id": msg_id}
    return {"peer": parts[0], "msg_id": msg_id}


def _category_menu():
    return "📂 Choose the most accurate category:\n\n" + "\n".join(
        f"{index}. {item[0]}" for index, item in enumerate(CATEGORIES, 1)
    ) + '\n\nSend a number or category name. Send "cancel" to stop.'


def _match_category(text):
    value = text.strip().lower()
    if value.isdigit():
        index = int(value) - 1
        return CATEGORIES[index] if 0 <= index < len(CATEGORIES) else None
    for category in CATEGORIES:
        if value == category[0].lower() or value in category[2]:
            return category
    return None


async def _resolve(client, event, parsed):
    try:
        peer = await client.get_input_entity(parsed["peer"])
        entity = await client.get_entity(peer)
    except Exception as exc:
        await _say(event, f"❌ Could not access that chat: {type(exc).__name__}")
        return None

    if parsed["msg_id"] is not None:
        try:
            message = await client.get_messages(peer, ids=parsed["msg_id"])
        except Exception:
            message = None
        if not message:
            await _say(event, "❌ Message not found or not accessible.")
            return None
    return {
        "input_peer": peer,
        "msg_id": parsed["msg_id"],
        "title": (
            getattr(entity, "title", None)
            or getattr(entity, "username", None)
            or getattr(entity, "first_name", None)
            or "Unknown"
        ),
    }


def _pick_option(options, category):
    for option in options:
        label = (option.text or "").lower()
        if any(keyword in label for keyword in category[2]):
            return option
    for option in options:
        if "other" in (option.text or "").lower():
            return option
    return options[0]


async def _submit_once(client, session):
    peer = session["input_peer"]
    msg_id = session["msg_id"]
    category = session["category"]
    reason_text = session["reason"][:512]

    if msg_id is None:
        await client(functions.account.ReportPeerRequest(
            peer=peer,
            reason=category[1](),
            message=reason_text,
        ))
        return

    if not _NEW_API:
        await client(functions.messages.ReportRequest(
            peer=peer,
            id=[msg_id],
            reason=category[1](),
            message=reason_text,
        ))
        return

    option = b""
    for _ in range(8):
        result = await client(functions.messages.ReportRequest(
            peer=peer,
            id=[msg_id],
            option=option,
            message=reason_text,
        ))
        kind = type(result).__name__
        if kind == "ReportResultReported":
            return
        if kind == "ReportResultAddComment":
            option = result.option
            continue
        if kind == "ReportResultChooseOption":
            option = _pick_option(result.options, category).option
            continue
        raise RuntimeError(f"Unexpected Telegram report response: {kind}")
    raise RuntimeError("Telegram report option flow did not finish.")


async def _start(client, event, link):
    parsed = _parse_link(link)
    if parsed is None:
        await _say(
            event,
            "❌ Invalid Telegram link.\n\n"
            "Usage: .report https://t.me/channel/123\n"
            "You can also use .report https://t.me/channel",
        )
        return

    target = await _resolve(client, event, parsed)
    if target is None:
        return

    _sessions[event.chat_id] = {
        "user_id": event.sender_id,
        "step": "category",
        "link": link,
        "input_peer": target["input_peer"],
        "msg_id": target["msg_id"],
        "title": target["title"],
        "category": None,
        "reason": None,
        "last": time.time(),
    }
    what = "message" if target["msg_id"] is not None else "chat"
    await _say(event, f"🎯 Target {what}: {target['title']}\n\n{_category_menu()}")


async def _continue(client, event, session, text):
    low = text.strip().lower()
    if session["step"] == "category":
        category = _match_category(text)
        if category is None:
            await _say(event, "❌ Invalid category.\n\n" + _category_menu())
            return
        session["category"] = category
        session["step"] = "reason"
        await _say(event, f"✅ Category: {category[0]}\n\nSend a truthful, concise reason for this report.")
        return

    if session["step"] == "reason":
        if not text.strip():
            await _say(event, "❌ Please provide a reason, or send cancel.")
            return
        session["reason"] = text.strip()[:512]
        session["step"] = "confirm"
        await _say(
            event,
            "📋 REPORT REVIEW\n\n"
            f"🔗 Target: {session['link']}\n"
            f"📂 Category: {session['category'][0]}\n"
            f"📝 Reason: {session['reason']}\n\n"
            "This submits one report only.\n"
            'Reply "confirm" to submit once, or "cancel" to abort.',
        )
        return

    if session["step"] == "confirm":
        if low != "confirm":
            await _say(event, 'Reply "confirm" to submit once, or "cancel" to abort.')
            return
        _sessions.pop(event.chat_id, None)
        try:
            await _submit_once(client, session)
            await _say(event, "✅ Telegram accepted the report request.")
        except Exception as exc:
            await _say(event, f"❌ Report request failed: {type(exc).__name__}: {exc}")


async def _handler(event, client):
    text = (getattr(event, "raw_text", None) or "").strip()
    if not text or (event.chat_id, event.id) in _own_messages:
        return

    parts = text.split(None, 1)
    command = parts[0].lower()

    if command == ".report":
        if len(parts) < 2:
            await _say(event, "Usage: .report <Telegram link>")
            return
        _sessions.pop(event.chat_id, None)
        await _start(client, event, parts[1].strip())
        return

    session = _sessions.get(event.chat_id)
    if not session or session["user_id"] != event.sender_id:
        return
    if time.time() - session["last"] > SESSION_TIMEOUT:
        _sessions.pop(event.chat_id, None)
        await _say(event, "⌛ Report session expired. Start again with .report <link>.")
        return

    session["last"] = time.time()
    if text.lower() == "cancel":
        _sessions.pop(event.chat_id, None)
        await _say(event, "🚫 Report cancelled.")
        return
    await _continue(client, event, session, text)


def init(client):
    global _client
    _client = client
    add_handler(
        "report_plugin",
        [".report <Telegram link> — Report a chat or message once after confirmation"],
        "Submit one confirmed report for content that genuinely violates Telegram rules",
    )

    async def handler(event):
        await _handler(event, client)

    client.add_event_handler(handler, events.NewMessage())
    print("[report-plugin] Loaded | single-report confirmation flow")
