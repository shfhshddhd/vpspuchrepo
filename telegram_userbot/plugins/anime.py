"""Simple anime recommendation plugin for hosted userbot clients."""

from telethon import events
from plugins.bot import add_handler

_client = None


def init(client_instance):
    """Keep the client supplied by the shared plugin loader."""
    global _client
    _client = client_instance


async def register_commands():
    """Register the .anime command and expose it in .help."""
    if _client is None:
        raise RuntimeError("Anime plugin cannot load without a hosted client.")

    add_handler(
        "anime",
        [".anime — Show 5 popular anime"],
        "Shows five popular anime recommendations",
    )

    async def anime_handler(event):
        message = (
            "🎌 **TOP 5 POPULAR ANIME**\n\n"
            "1. **One Piece**\n"
            "2. **Naruto: Shippuden**\n"
            "3. **Dragon Ball Z**\n"
            "4. **Attack on Titan**\n"
            "5. **Demon Slayer: Kimetsu no Yaiba**"
        )
        await event.reply(message)

    _client.add_event_handler(
        anime_handler,
        events.NewMessage(pattern=r"^\\s*\\.anime\\s*$"),
    )
