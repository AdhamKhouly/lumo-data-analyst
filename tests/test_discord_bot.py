"""Message routing and formatting, with plain objects standing in for Discord's."""
from types import SimpleNamespace

from src.discord_bot import parse_ids, should_handle, split_message, strip_mention

BOT = 42


def message(content="hi", guild=True, channel_id=1, mentions=(), author_id=7, bot=False):
    return SimpleNamespace(content=content, guild=SimpleNamespace(id=99) if guild else None,
                           channel=SimpleNamespace(id=channel_id, parent_id=None),
                           mentions=[SimpleNamespace(id=m) for m in mentions],
                           author=SimpleNamespace(id=author_id, bot=bot))


def test_routing_rules():
    assert should_handle(message(guild=False), BOT, set(), set())                     # a DM
    assert not should_handle(message(), BOT, set(), set())                            # server, no mention
    assert should_handle(message(mentions=[BOT]), BOT, set(), set())                  # server, @mentioned
    assert should_handle(message(channel_id=5), BOT, {5}, set())                      # open channel
    assert not should_handle(message(guild=False, bot=True), BOT, set(), set())       # another bot
    assert not should_handle(message(guild=False, content="  "), BOT, set(), set())   # nothing to answer
    assert not should_handle(message(guild=False, author_id=8), BOT, set(), {7})      # not on the allow list


def test_mention_is_stripped_and_ids_parsed():
    assert strip_mention(f"<@{BOT}> how was   week 3?", BOT) == "how was week 3?"
    assert parse_ids("123, <#456> junk") == {123, 456}


def test_long_answers_split_on_paragraphs():
    text = "\n\n".join(f"paragraph {i} " + "x" * 500 for i in range(8))
    chunks = split_message(text, limit=1900)
    assert len(chunks) > 1 and all(len(c) <= 1900 for c in chunks)
    assert chunks[0].startswith("paragraph 0") and "".join(chunks).count("paragraph") == 8
