"""
Watch Party — group members vote on what to watch. When voting ends, the
bot searches the winning title (using the same fuzzy + 🧠 Smart Search
pipeline as normal search) and posts deep-link buttons — same delivery
mechanism the bot already uses everywhere else.
"""
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import WATCHPARTY_DURATION, MAX_BTN
from database.ia_filterdb import get_search_results
from utils import temp, get_size, formate_file_name

# In-memory vote store: message_id -> {"options": [...], "votes": {user_id: idx}, "chat_id": int}
_PARTIES = {}


def _party_text(options, votes):
    counts = [0] * len(options)
    for idx in votes.values():
        counts[idx] += 1
    lines = ["🎉 <b>ᴡᴀᴛᴄʜ ᴘᴀʀᴛʏ — ᴠᴏᴛᴇ ᴡʜᴀᴛ ᴛᴏ ᴡᴀᴛᴄʜ!</b>\n"]
    for i, opt in enumerate(options):
        lines.append(f"{i + 1}. {opt} — <b>{counts[i]}</b> ᴠᴏᴛᴇ(s)")
    lines.append(f"\n⏳ ᴠᴏᴛɪɴɢ ᴇɴᴅs ɪɴ {WATCHPARTY_DURATION // 60} ᴍɪɴ. ᴛᴀᴘ ᴀ ʙᴜᴛᴛᴏɴ ᴛᴏ ᴠᴏᴛᴇ!")
    return "\n".join(lines)


def _party_buttons(options, message_id):
    buttons = []
    for i, opt in enumerate(options):
        label = opt if len(opt) <= 30 else opt[:27] + "..."
        buttons.append([InlineKeyboardButton(f"🗳️ {label}", callback_data=f"party_vote#{message_id}#{i}")])
    return InlineKeyboardMarkup(buttons)


@Client.on_message(filters.command("watchparty") & filters.group)
async def start_party(client, message):
    if len(message.command) < 2:
        return await message.reply_text(
            "Usage: <code>/watchparty Movie 1 | Movie 2 | Movie 3</code>\n"
            "(2-8 options, separated by <code>|</code>)"
        )
    raw = message.text.split(None, 1)[1]
    options = [o.strip() for o in raw.split("|") if o.strip()]
    if not (2 <= len(options) <= 8):
        return await message.reply_text("Please give between 2 and 8 options, separated by <code>|</code>.")

    sent = await message.reply_text(_party_text(options, {}))
    _PARTIES[sent.id] = {"options": options, "votes": {}, "chat_id": message.chat.id}
    await sent.edit_reply_markup(_party_buttons(options, sent.id))

    asyncio.create_task(_auto_end_party(client, sent.id, WATCHPARTY_DURATION))


@Client.on_callback_query(filters.regex(r"^party_vote#"))
async def cast_vote(client, query):
    _, msg_id, idx = query.data.split("#")
    msg_id, idx = int(msg_id), int(idx)
    party = _PARTIES.get(msg_id)
    if not party:
        return await query.answer("This party has ended.", show_alert=True)
    party["votes"][query.from_user.id] = idx
    await query.message.edit_text(
        _party_text(party["options"], party["votes"]),
        reply_markup=_party_buttons(party["options"], msg_id)
    )
    await query.answer(f"Voted: {party['options'][idx]}")


@Client.on_message(filters.command("endparty") & filters.group)
async def manual_end_party(client, message):
    if not message.reply_to_message or message.reply_to_message.id not in _PARTIES:
        return await message.reply_text("Reply to an active Watch Party message with /endparty.")
    await _end_party(client, message.reply_to_message.id)


async def _auto_end_party(client, message_id, delay):
    await asyncio.sleep(delay)
    if message_id in _PARTIES:
        await _end_party(client, message_id)


async def _end_party(client, message_id):
    party = _PARTIES.pop(message_id, None)
    if not party:
        return
    options, votes, chat_id = party["options"], party["votes"], party["chat_id"]
    counts = [0] * len(options)
    for idx in votes.values():
        counts[idx] += 1

    if not votes:
        return await client.send_message(chat_id, "🎉 Watch Party ended — nobody voted, maybe next time!")

    winner_idx = counts.index(max(counts))
    winner = options[winner_idx]

    await client.send_message(chat_id, f"🏆 <b>Winner: {winner}</b> with {counts[winner_idx]} vote(s)!\n\n🔎 Searching...")

    files, _, total = await get_search_results(winner, max_results=MAX_BTN)
    if total == 0:
        return await client.send_message(chat_id, f"❌ Couldn't find <b>{winner}</b> in the database.")

    buttons = [
        [InlineKeyboardButton(
            text=f"🔗 {get_size(file.file_size)}≽ {formate_file_name(file.file_name)}",
            url=f"https://telegram.dog/{temp.U_NAME}?start=file_{chat_id}_{file.file_id}",
        )]
        for file in files
    ]
    await client.send_message(
        chat_id,
        f"📁 Found <b>{total}</b> result(s) for <b>{winner}</b> — tap to get in your PM:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
