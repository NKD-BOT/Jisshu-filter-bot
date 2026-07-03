"""
Voice Search — send a voice message describing what you want, and the bot
transcribes it (via the free Google Web Speech recognizer, no API key
needed) and runs it through the exact same search pipeline as a normal
text query (fuzzy spelling correction + 🧠 Smart Search included).
"""
import os
import tempfile
import static_ffmpeg
import speech_recognition as sr
from pydub import AudioSegment
from pyrogram import Client, filters

from plugins.pm_filter import auto_filter

# Ensures a working ffmpeg + ffprobe are on PATH regardless of the hosting
# platform (Docker/Nixpacks/Heroku-buildpack/Koyeb/etc). Downloads a small
# portable static binary once on first run — no system-level apt install
# needed anywhere.
static_ffmpeg.add_paths()


@Client.on_message(filters.voice & filters.incoming & (filters.private | filters.group))
async def voice_search(client, message):
    status = await message.reply_text("🎙️ ʟɪsᴛᴇɴɪɴɢ...")
    with tempfile.TemporaryDirectory() as tmp:
        ogg_path = os.path.join(tmp, "voice.ogg")
        wav_path = os.path.join(tmp, "voice.wav")
        await message.download(file_name=ogg_path)

        try:
            AudioSegment.from_file(ogg_path).export(wav_path, format="wav")
        except Exception as e:
            return await status.edit_text(f"❌ Couldn't process the audio: {e}")

        recognizer = sr.Recognizer()
        try:
            with sr.AudioFile(wav_path) as source:
                audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data)
        except sr.UnknownValueError:
            return await status.edit_text("❌ Couldn't understand the audio. Please speak clearly and try again.")
        except sr.RequestError as e:
            return await status.edit_text(f"❌ Speech recognition service unavailable right now: {e}")
        except Exception as e:
            return await status.edit_text(f"❌ Something went wrong: {e}")

    await status.edit_text(f"🎙️ ʜᴇᴀʀᴅ: <b>{text}</b>\n\n🔎 sᴇᴀʀᴄʜɪɴɢ...")
    message.text = text  # same pattern already used by the spell-check flow in pm_filter.py
    await auto_filter(client, message)
