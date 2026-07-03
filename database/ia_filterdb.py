from struct import pack
import re
import base64
import asyncio
import difflib
from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError
from umongo import Instance, Document, fields
from motor.motor_asyncio import AsyncIOMotorClient
from marshmallow.exceptions import ValidationError
from info import FILES_DATABASE, DATABASE_NAME, COLLECTION_NAME, MAX_BTN

client = AsyncIOMotorClient(FILES_DATABASE)
mydb = client[DATABASE_NAME]
instance = Instance.from_db(mydb)


@instance.register
class Media(Document):
    file_id = fields.StrField(attribute="_id")
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    mime_type = fields.StrField(allow_none=True)
    caption = fields.StrField(allow_none=True)
    file_type = fields.StrField(allow_none=True)

    class Meta:
        indexes = ("$file_name",)
        collection_name = COLLECTION_NAME


async def get_files_db_size():
    return (await mydb.command("dbstats"))["dataSize"]


# ==========================================================================
# Spell Correction (fuzzy "did you mean" search)
# --------------------------------------------------------------------------
# Builds an in-memory word corpus from every indexed file_name and uses it
# to auto-correct misspelled search queries (e.g. "Heros" -> "Heroes")
# before falling back to a "no results" reply.
# ==========================================================================
SPELL_CORPUS = set()
_CORPUS_LOCK = asyncio.Lock()


async def build_spell_corpus():
    """(Re)builds the in-memory word corpus used for fuzzy spelling
    correction, from all currently indexed file names."""
    global SPELL_CORPUS
    words = set()
    try:
        cursor = mydb[COLLECTION_NAME].find({}, {"file_name": 1})
        async for doc in cursor:
            name = doc.get("file_name", "") or ""
            for w in re.split(r"[^A-Za-z0-9]+", name):
                w = w.lower()
                if len(w) >= 3 and not w.isdigit():
                    words.add(w)
    except Exception as e:
        print(f"[SpellCorpus] Failed to build corpus: {e}")
        return
    async with _CORPUS_LOCK:
        SPELL_CORPUS = words
    print(f"[SpellCorpus] Built corpus with {len(words)} unique words")


async def refresh_spell_corpus_loop(interval_seconds: int = 3 * 60 * 60):
    """Background loop: rebuilds the spell-check corpus periodically so it
    stays fresh as new files get indexed."""
    while True:
        await build_spell_corpus()
        await asyncio.sleep(interval_seconds)


def _correct_query_spelling(query: str):
    """Attempts to auto-correct misspelled words in a search query using
    the in-memory corpus of known file-name words.
    Returns (corrected_query, changed: bool)."""
    if not SPELL_CORPUS:
        return query, False
    words = query.split(" ")
    changed = False
    corrected_words = []
    for w in words:
        clean = re.sub(r"[^A-Za-z0-9]", "", w).lower()
        if not clean or len(clean) < 3 or clean in SPELL_CORPUS:
            corrected_words.append(w)
            continue
        matches = difflib.get_close_matches(clean, SPELL_CORPUS, n=1, cutoff=0.75)
        if matches:
            corrected_words.append(matches[0])
            changed = True
        else:
            corrected_words.append(w)
    return " ".join(corrected_words), changed


async def save_file(media):
    """Save file in database"""

    # TODO: Find better way to get same file_id for same media to avoid duplicates
    file_id, file_ref = unpack_new_file_id(media.file_id)
    file_name = re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name))
    try:
        file = Media(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=media.file_size,
            mime_type=media.mime_type,
            caption=media.caption.html if media.caption else None,
            file_type=media.mime_type.split("/")[0],
        )
    except ValidationError:
        print("Error occurred while saving file in database")
        return "err"
    else:
        try:
            await file.commit()
        except DuplicateKeyError:
            print(
                f'{getattr(media, "file_name", "NO_FILE")} is already saved in database'
            )
            return "dup"
        else:
            print(f'{getattr(media, "file_name", "NO_FILE")} is saved to database')
            return "suc"


async def get_search_results(query, max_results=MAX_BTN, offset=0, lang=None, _spell_retry=True):
    files, next_offset, total_results = await _get_search_results_raw(
        query, max_results=max_results, offset=offset, lang=lang
    )
    if total_results == 0 and _spell_retry:
        corrected, changed = _correct_query_spelling(query)
        if changed and corrected.strip().lower() != query.strip().lower():
            c_files, c_next_offset, c_total = await _get_search_results_raw(
                corrected, max_results=max_results, offset=offset, lang=lang
            )
            if c_total > 0:
                print(f"[SpellCorpus] '{query}' had 0 results, auto-corrected to '{corrected}'")
                return c_files, c_next_offset, c_total

        # 🧠 Smart Search: spelling-correction couldn't help either — try
        # asking TMDb to understand a natural-language query and resolve it
        # to a real title (e.g. "that spiderman movie with tobey" -> "Spider-Man").
        try:
            from smart_search import smart_resolve
            resolved = await smart_resolve(query)
        except Exception as e:
            print(f"[SmartSearch] failed: {e}")
            resolved = None
        if resolved and resolved.strip().lower() != query.strip().lower():
            s_files, s_next_offset, s_total = await _get_search_results_raw(
                resolved, max_results=max_results, offset=offset, lang=lang
            )
            if s_total > 0:
                print(f"[SmartSearch] '{query}' had 0 results, resolved to '{resolved}'")
                return s_files, s_next_offset, s_total

    return files, next_offset, total_results


async def _get_search_results_raw(query, max_results=MAX_BTN, offset=0, lang=None):
    query = query.strip()
    if not query:
        raw_pattern = "."
    elif " " not in query:
        raw_pattern = r"(\b|[\.\+\-_])" + query + r"(\b|[\.\+\-_])"
    else:
        raw_pattern = query.replace(" ", r".*[\s\.\+\-_]")
    try:
        regex = re.compile(raw_pattern, flags=re.IGNORECASE)
    except:
        regex = query
    filter = {"file_name": regex}
    cursor = Media.find(filter)
    cursor.sort("$natural", -1)
    if lang:
        lang_files = [file async for file in cursor if lang in file.file_name.lower()]
        files = lang_files[offset:][:max_results]
        total_results = len(lang_files)
        next_offset = offset + max_results
        if next_offset >= total_results:
            next_offset = ""
        return files, next_offset, total_results
    cursor.skip(offset).limit(max_results)
    files = await cursor.to_list(length=max_results)
    total_results = await Media.count_documents(filter)
    next_offset = offset + max_results
    if next_offset >= total_results:
        next_offset = ""
    return files, next_offset, total_results


async def get_bad_files(query, file_type=None, offset=0, filter=False):
    query = query.strip()
    if not query:
        raw_pattern = "."
    elif " " not in query:
        raw_pattern = r"(\b|[\.\+\-_])" + query + r"(\b|[\.\+\-_])"
    else:
        raw_pattern = query.replace(" ", r".*[\s\.\+\-_]")
    try:
        regex = re.compile(raw_pattern, flags=re.IGNORECASE)
    except:
        return []
    filter = {"file_name": regex}
    if file_type:
        filter["file_type"] = file_type
    total_results = await Media.count_documents(filter)
    cursor = Media.find(filter)
    cursor.sort("$natural", -1)
    files = await cursor.to_list(length=total_results)
    return files, total_results


async def get_file_details(query):
    filter = {"file_id": query}
    cursor = Media.find(filter)
    filedetails = await cursor.to_list(length=1)
    return filedetails


def encode_file_id(s: bytes) -> str:
    r = b""
    n = 0
    for i in s + bytes([22]) + bytes([4]):
        if i == 0:
            n += 1
        else:
            if n:
                r += b"\x00" + bytes([n])
                n = 0
            r += bytes([i])
    return base64.urlsafe_b64encode(r).decode().rstrip("=")


def encode_file_ref(file_ref: bytes) -> str:
    return base64.urlsafe_b64encode(file_ref).decode().rstrip("=")


def unpack_new_file_id(new_file_id):
    """Return file_id, file_ref"""
    decoded = FileId.decode(new_file_id)
    file_id = encode_file_id(
        pack(
            "<iiqq",
            int(decoded.file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash,
        )
    )
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref
