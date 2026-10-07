"""Lumo on Discord.

    python -m src.discord_bot

The bot answers direct messages, any message in the channels listed in DISCORD_CHANNEL_IDS,
and @mentions elsewhere. Each user keeps a separate conversation per channel, so follow-up
questions work ("what about week 8?") and two people never share context. `/clear` forgets
your conversation; `/weeks` shows what data is loaded.

Nothing in this file does analysis: it turns Discord messages into Lumo.ask() calls and
sends the answer back in chunks small enough for Discord's 2000-character limit.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from typing import Any

from dotenv import load_dotenv

from .agent import Conversation, Lumo
from .analytics import list_weeks
from .database import DEFAULT_DB_PATH, Database

log = logging.getLogger("lumo.discord")
DISCORD_LIMIT = 1900  # a little under 2000 to leave room for formatting


def parse_ids(raw: str | None) -> set[int]:
    """'123, 456' -> {123, 456}; anything that is not a number is ignored."""
    ids = set()
    for chunk in (raw or "").replace(",", " ").split():
        cleaned = chunk.strip("<#@!>")
        if cleaned.isdigit():
            ids.add(int(cleaned))
    return ids


def should_handle(message: Any, bot_id: int, open_channels: set[int], allowed_users: set[int]) -> bool:
    """Is this message for us? DMs always; open channels always; elsewhere only on @mention."""
    author = getattr(message, "author", None)
    if author is None or getattr(author, "bot", False) or getattr(author, "id", None) == bot_id:
        return False
    if not (getattr(message, "content", "") or "").strip():
        return False
    if allowed_users and author.id not in allowed_users:
        return False
    if getattr(message, "guild", None) is None:
        return True
    channel = getattr(message, "channel", None)
    if channel is not None and (getattr(channel, "id", None) in open_channels
                                or getattr(channel, "parent_id", None) in open_channels):
        return True
    return any(getattr(u, "id", None) == bot_id for u in (getattr(message, "mentions", None) or []))


def strip_mention(content: str, bot_id: int) -> str:
    return " ".join(re.sub(rf"<@!?{bot_id}>", " ", content or "").split())


def split_message(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """Split a long answer on paragraph, then line, boundaries so nothing is cut mid-sentence."""
    text = (text or "").strip() or "(no answer)"
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for part in re.split(r"(\n\n|\n)", text):
        if len(current) + len(part) <= limit:
            current += part
            continue
        if current.strip():
            chunks.append(current.strip())
        current = ""
        while len(part) > limit:  # a single huge paragraph: hard split
            chunks.append(part[:limit])
            part = part[limit:]
        current = part
    if current.strip():
        chunks.append(current.strip())
    return chunks


def conversation_key(message: Any) -> str:
    guild = getattr(message, "guild", None)
    channel_id = getattr(getattr(message, "channel", None), "id", 0)
    return f"dm:{message.author.id}" if guild is None else f"guild:{guild.id}:{channel_id}:{message.author.id}"


def run() -> int:
    import discord
    from discord import app_commands

    load_dotenv()
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        print("DISCORD_BOT_TOKEN is not set. Copy .env.example to .env and add your bot token.", file=sys.stderr)
        return 2
    if not DEFAULT_DB_PATH.exists():
        print(f"No database at {DEFAULT_DB_PATH.name}. Run `python -m src.ingest` first.", file=sys.stderr)
        return 2
    open_channels = parse_ids(os.environ.get("DISCORD_CHANNEL_IDS"))
    allowed_users = parse_ids(os.environ.get("DISCORD_ALLOWED_USER_IDS"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    db = Database(DEFAULT_DB_PATH, read_only=True)
    lumo = Lumo(db)
    conversations: dict[str, Conversation] = {}
    busy = asyncio.Semaphore(2)  # at most two questions in flight at once

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    @client.event
    async def on_ready() -> None:
        await tree.sync()
        print(f"Lumo is connected as {client.user}. Press Ctrl+C to stop.")

    @client.event
    async def on_message(message: discord.Message) -> None:
        if client.user is None or not should_handle(message, client.user.id, open_channels, allowed_users):
            return
        question = strip_mention(message.content, client.user.id)
        if not question:
            await message.reply("Ask me anything about the weekly reports, for example: "
                                "\"How did revenue change from week 3 to week 8?\"", mention_author=False)
            return
        key = conversation_key(message)
        conversation = conversations.setdefault(key, Conversation())
        log.info("question from %s (%d earlier turns)", key, conversation.turns)
        async with busy, message.channel.typing():
            try:
                answer = await asyncio.to_thread(lumo.ask, question, conversation)
            except Exception:  # noqa: BLE001 - never crash the bot on one bad question
                log.exception("failed to answer")
                await message.reply("Something went wrong while answering that. Please try again.", mention_author=False)
                return
        for i, chunk in enumerate(split_message(answer.text)):
            await (message.reply(chunk, mention_author=False) if i == 0 else message.channel.send(chunk))

    @tree.command(name="clear", description="Forget our conversation and start fresh")
    async def clear_command(interaction: discord.Interaction) -> None:
        key = (f"dm:{interaction.user.id}" if interaction.guild_id is None
               else f"guild:{interaction.guild_id}:{getattr(interaction.channel, 'id', 0)}:{interaction.user.id}")
        had = key in conversations and conversations[key].turns > 0
        conversations.pop(key, None)
        await interaction.response.send_message("Conversation cleared." if had else "Nothing to clear yet.", ephemeral=True)

    @tree.command(name="weeks", description="Which weeks of data are loaded")
    async def weeks_command(interaction: discord.Interaction) -> None:
        info = list_weeks(db)
        weeks = info["weeks"]
        text = (f"{len(weeks)} weeks loaded for {info['company']}: week {weeks[0]} to week {weeks[-1]}."
                if weeks else "No data loaded yet.")
        await interaction.response.send_message(text)

    try:
        client.run(token, log_handler=None)
    except discord.LoginFailure:
        print("Discord rejected the bot token. Check DISCORD_BOT_TOKEN in .env.", file=sys.stderr)
        return 2
    except discord.PrivilegedIntentsRequired:
        print("Enable the MESSAGE CONTENT intent for the bot in the Discord Developer Portal.", file=sys.stderr)
        return 2
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(run())
