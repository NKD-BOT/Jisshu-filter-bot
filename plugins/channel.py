# --| Modified for Jisshu Repo (SilentX + DreamX Features) |--#
import re
import logging
import asyncio
from datetime import datetime
from collections import defaultdict
from plugins.Dreamxfutures.Imdbposter import get_movie_detailsx, fetch_image, get_movie_details
from database.users_chats_db import db
from pyrogram import Client, filters, enums
from info import CHANNELS, MOVIE_UPDATE_CHANNEL, LINK_PREVIEW, ABOVE_PREVIEW, BAD_WORDS, LANDSCAPE_POSTER, TMDB_POSTER, LOG_CHANNEL
from Script import script
from database.ia_filterdb import save_file
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils import temp
from pymongo.errors import PyMongoError, DuplicateKeyError
from pyrogram.errors import MessageIdInvalid, MessageNotModified, FloodWait
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ==============================
# CONSTANTS + CONFIG
# ==============================
IGNORE_WORDS = {
    "rarbg", "dub", "sub", "sample", "mkv", "aac", "combined",
    "action", "adventure", "animation", "biography", "comedy", "crime",
    "documentary", "drama", "family", "fantasy", "film-noir", "history",
    "horror", "music", "musical", "mystery", "romance", "sci-fi", "sport",
    "thriller", "war", "western", "hdcam", "hdtc", "camrip", "ts", "tc",
    "telesync", "dvdscr", "dvdrip", "predvd", "webrip", "web-dl", "tvrip",
    "hdtv", "web dl", "webdl", "bluray", "brrip", "bdrip", "360p", "480p",
    "720p", "1080p", "2160p", "4k", "1440p", "540p", "240p", "140p", "hevc",
    "hdrip", "hin", "hindi", "tam", "tamil", "kan", "kannada", "tel", "telugu",
    "mal", "malayalam", "eng", "english", "pun", "punjabi", "ben", "bengali",
    "mar", "marathi", "guj", "gujarati", "urd", "urdu", "kor", "korean", "jpn",
    "japanese", "nf", "netflix", "sonyliv", "sony", "sliv", "amzn", "prime",
    "primevideo", "hotstar", "zee5", "jio", "jhs", "aha", "hbo", "paramount",
    "apple", "hoichoi", "sunnxt", "viki"
} | BAD_WORDS

CAPTION_LANGUAGES = {
    "hin": "Hindi", "hindi": "Hindi",
    "tam": "Tamil", "tamil": "Tamil",
    "kan": "Kannada", "kannada": "Kannada",
    "tel": "Telugu", "telugu": "Telugu",
    "mal": "Malayalam", "malayalam": "Malayalam",
    "eng": "English", "english": "English",
    "pun": "Punjabi", "punjabi": "Punjabi",
    "ben": "Bengali", "bengali": "Bengali",
    "mar": "Marathi", "marathi": "Marathi",
    "guj": "Gujarati", "gujarati": "Gujarati",
    "urd": "Urdu", "urdu": "Urdu",
    "kor": "Korean", "korean": "Korean",
    "jpn": "Japanese", "japanese": "Japanese",
}

OTT_PLATFORMS = {
    "nf": "Netflix", "netflix": "Netflix",
    "sonyliv": "SonyLiv", "sony": "SonyLiv", "sliv": "SonyLiv",
    "amzn": "Amazon Prime Video", "prime": "Amazon Prime Video", "primevideo": "Amazon Prime Video",
    "hotstar": "Disney+ Hotstar", "zee5": "Zee5",
    "jio": "JioHotstar", "jhs": "JioHotstar",
    "aha": "Aha", "hbo": "HBO Max", "paramount": "Paramount+",
    "apple": "Apple TV+", "hoichoi": "Hoichoi", "sunnxt": "Sun NXT", "viki": "Viki"
}

STANDARD_GENRES = {
    'Action', 'Adventure', 'Animation', 'Biography', 'Comedy', 'Crime', 'Documentary',
    'Drama', 'Family', 'Fantasy', 'Film-Noir', 'History', 'Horror', 'Music',
    'Musical', 'Mystery', 'Romance', 'Sci-Fi', 'Sport', 'Thriller', 'War', 'Western'
}

# Regex Patterns
CLEAN_PATTERN = re.compile(r'@[^ \n\r\t\.,:;!?()\[\]{}<>\\/"\'=_%]+|\bwww\.[^\s\]\)]+')
NORMALIZE_PATTERN = re.compile(r"[._]+|[()\[\]{}:;'–!,.?_]")
QUALITY_PATTERN = re.compile(r"\b(?:480p|720p|1080p|2160p|4k|hevc|hdrip|webrip|web-dl|bluray|hdtv)\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"(19|20)\d{2}")

MEDIA_FILTER = filters.document | filters.video | filters.audio
locks = defaultdict(asyncio.Lock)
pending_updates = {}

# ==============================
# HELPER FUNCTIONS
# ==============================
def clean_mentions_links(text: str) -> str:
    return CLEAN_PATTERN.sub("", text or "").strip()

def normalize(s: str) -> str:
    s = NORMALIZE_PATTERN.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()

def remove_ignored_words(text: str) -> str:
    IGNORE_WORDS_LOWER = {w.lower() for w in IGNORE_WORDS}
    return " ".join(word for word in text.split() if word.lower() not in IGNORE_WORDS_LOWER)

def get_qualities(text: str) -> str:
    qualities = QUALITY_PATTERN.findall(text)
    return ", ".join(qualities) if qualities else "N/A"

def extract_ott_platform(text: str) -> str:
    text = text.lower()
    platforms = {plat for key, plat in OTT_PLATFORMS.items() if key in text}
    return " | ".join(platforms) if platforms else "N/A"

# ==============================
# MAIN HANDLER
# ==============================
@Client.on_message(filters.chat(CHANNELS) & MEDIA_FILTER)
async def media_handler(bot, message):
    media = next(
        (getattr(message, ft) for ft in ("document", "video", "audio")
         if getattr(message, ft, None)),
        None
    )
    if not media:
        return

    media.caption = message.caption or ""
    success, info = await save_file(media)
    if not success:
        return

    try:
        if await db.movie_update_status(bot.me.id):
            await process_and_send_update(bot, media.file_name, media.caption)
    except Exception:
        logger.exception("Error processing media")

# ==============================
# PROCESSOR
# ==============================
async def process_and_send_update(bot, filename, caption):
    try:
        # file info extract
        base_name = normalize(remove_ignored_words(normalize(filename)))
        year_match = YEAR_PATTERN.search(filename)
        if year_match and year_match.group(0) not in base_name:
            base_name += f" {year_match.group(0)}"

        lock = locks[base_name]
        async with lock:
            await _process_with_lock(bot, filename, caption, base_name)
    except Exception as e:
        logger.error(f"Processing failed: {e}")

async def _process_with_lock(bot, filename, caption, base_name):
    if not hasattr(db, 'movie_updates'):
        db.movie_updates = db.db.movie_updates

    movie_doc = await db.movie_updates.find_one({"_id": base_name})
    file_data = {
        "filename": filename,
        "quality": get_qualities(caption),
        "language": "Hindi" if "hindi" in caption.lower() else "N/A",
        "ott_platform": extract_ott_platform(caption),
        "timestamp": datetime.now(),
    }

    if not movie_doc:
        details = await get_movie_details(base_name) or {}
        movie_doc = {
            "_id": base_name,
            "files": [file_data],
            "poster_url": details.get("poster_url"),
            "genres": details.get("genres", "N/A"),
            "rating": details.get("rating", "N/A"),
            "imdb_url": details.get("url", ""),
            "year": details.get("year"),
            "message_id": None,
            "is_photo": False
        }
        try:
            await db.movie_updates.insert_one(movie_doc)
            await send_movie_update(bot, base_name)
        except DuplicateKeyError:
            pass
    else:
        if any(f["filename"] == filename for f in movie_doc["files"]):
            return
        await db.movie_updates.update_one(
            {"_id": base_name},
            {"$push": {"files": file_data}}
        )
        movie_doc["files"].append(file_data)

# ==============================
# SEND + UPDATE MESSAGE
# ==============================
async def send_movie_update(bot, base_name):
    try:
        movie_doc = await db.movie_updates.find_one({"_id": base_name})
        if not movie_doc:
            return None

        text = generate_movie_message(movie_doc, base_name)
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                'ɢᴇᴛ ғɪʟᴇs',
                url=f"https://t.me/{temp.U_NAME}?start=getfile-{base_name.replace(' ', '-')}"
            )
        ]])

        if movie_doc.get("poster_url") and not LINK_PREVIEW:
            resized_poster = await fetch_image(movie_doc["poster_url"], size=(1280, 720))
            msg = await bot.send_photo(
                chat_id=MOVIE_UPDATE_CHANNEL,
                photo=resized_poster,
                caption=text,
                reply_markup=buttons,
                parse_mode=enums.ParseMode.HTML
            )
            is_photo = True
        else:
            msg = await bot.send_message(
                chat_id=MOVIE_UPDATE_CHANNEL,
                text=text,
                reply_markup=buttons,
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=not LINK_PREVIEW
            )
            is_photo = False

        await db.movie_updates.update_one(
            {"_id": base_name},
            {"$set": {"message_id": msg.id, "is_photo": is_photo}}
        )
        return msg
    except Exception as e:
        logger.error(f"Failed to send movie update: {e}")
        await bot.send_message(LOG_CHANNEL, f"❌ Movie Update Failed\n\n{e}")
    return None

def generate_movie_message(movie_doc, base_name):
    qualities = {f["quality"] for f in movie_doc["files"] if f.get("quality")}
    langs = {f["language"] for f in movie_doc["files"] if f.get("language")}
    otts = {f["ott_platform"] for f in movie_doc["files"] if f.get("ott_platform")}

    return script.MOVIE_UPDATE_NOTIFY_TXT.format(
        poster_url=movie_doc.get("poster_url", ""),
        imdb_url=movie_doc.get("imdb_url", ""),
        filename=base_name,
        tag="#MOVIE",
        genres=movie_doc.get("genres", "N/A"),
        ott=", ".join(otts) if otts else "N/A",
        quality=", ".join(qualities) if qualities else "N/A",
        language=", ".join(langs) if langs else "N/A",
        episodes="",
        rating=movie_doc.get("rating", "N/A"),
        search_link=temp.B_LINK
    )
