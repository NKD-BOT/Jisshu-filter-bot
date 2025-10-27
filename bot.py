import os
import sys
import glob
import importlib
from pathlib import Path
from pyrogram import idle
import logging
import logging.config
import asyncio

# Get logging configurations
logging.config.fileConfig("logging.conf")
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("imdbpy").setLevel(logging.ERROR)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("aiohttp").setLevel(logging.ERROR)
logging.getLogger("aiohttp.web").setLevel(logging.ERROR)

from pyrogram import __version__
from pyrogram.raw.all import layer
from database.ia_filterdb import Media
from database.users_chats_db import db
from info import *
from utils import temp
from Script import script
from datetime import date, datetime
import pytz
from aiohttp import web
from plugins import web_server, check_expired_premium
import pyrogram.utils

from Jisshu.bot import JisshuBot
from Jisshu.util.keepalive import ping_server
from Jisshu.bot.clients import initialize_clients

ppath = "plugins/*.py"
files = glob.glob(ppath)
# start client (don't await here)
JisshuBot.start()
loop = asyncio.get_event_loop()

pyrogram.utils.MIN_CHANNEL_ID = -1009147483647

# ---------------------------
# Safe function to send restart notice to all users
# ---------------------------
async def send_restart_notice_to_all():
    try:
        # Adjust according to your DB API. Example returns an AsyncIOMotorCursor
        users_cursor = await db.get_all_users_cursor() if hasattr(db, "get_all_users_cursor") else None

        users = []
        # If db provides a cursor (motor) with to_list
        if users_cursor is not None:
            if hasattr(users_cursor, "to_list"):
                try:
                    users = await users_cursor.to_list(length=None)
                except Exception:
                    # fallback to async iteration
                    users = []
                    async for u in users_cursor:
                        users.append(u)
            else:
                # If it's an async generator/cursor
                try:
                    async for u in users_cursor:
                        users.append(u)
                except Exception:
                    users = []
        else:
            # fallback: if db has a simple method returning list
            if hasattr(db, "get_all_users"):
                try:
                    maybe_users = await db.get_all_users()
                    # if it's a cursor, convert to list
                    if hasattr(maybe_users, "to_list"):
                        users = await maybe_users.to_list(length=None)
                    else:
                        users = list(maybe_users)
                except Exception:
                    users = []

        # users now should be a list of dicts or ids
        if not users:
            return

        for u in users:
            try:
                # adapt to your user document schema
                # common fields: "user_id", "id", or the object could be plain int
                if isinstance(u, dict):
                    uid = u.get("user_id") or u.get("id") or u.get("_id")
                else:
                    uid = u

                if not uid:
                    continue

                # send a safe message: catch per-user errors and continue
                try:
                    await JisshuBot.send_message(
                        chat_id=int(uid),
                        text=script.RESTART_BROADCAST_TEXT
                        if hasattr(script, "RESTART_BROADCAST_TEXT")
                        else "Bot restarted. Back online!",
                    )
                except Exception:
                    # ignore send errors (blocked users, invalid id, floodwait etc)
                    pass

                # small delay to avoid hitting Telegram rate limits
                await asyncio.sleep(0.15)

            except Exception:
                # never let a single user break the whole loop
                continue

    except Exception as e:
        logging.exception("send_restart_notice_to_all failed: %s", e)


# ---------------------------
# small health route (if your web_server doesn't have it)
# ---------------------------
async def _root_health(request):
    return web.Response(text="OK", status=200)

# ---------------------------
# Modified Jisshu_start (only key changes shown)
# ---------------------------
async def Jisshu_start():
    print("\n")
    print("Credit - Telegram @JISSHU_BOTS")
    bot_info = await JisshuBot.get_me()
    JisshuBot.username = bot_info.username
    await initialize_clients()
    for name in files:
        with open(name) as a:
            patt = Path(a.name)
            plugin_name = patt.stem.replace(".py", "")
            plugins_dir = Path(f"plugins/{plugin_name}.py")
            import_path = "plugins.{}".format(plugin_name)
            spec = importlib.util.spec_from_file_location(import_path, plugins_dir)
            load = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(load)
            sys.modules["plugins." + plugin_name] = load
            print("JisshuBot Imported => " + plugin_name)
    if ON_HEROKU:
        asyncio.create_task(ping_server())
    b_users, b_chats = await db.get_banned()
    temp.BANNED_USERS = b_users
    temp.BANNED_CHATS = b_chats
    await Media.ensure_indexes()
    me = await JisshuBot.get_me()
    temp.ME = me.id
    temp.U_NAME = me.username
    temp.B_NAME = me.first_name
    temp.B_LINK = me.mention
    JisshuBot.username = "@" + me.username
    JisshuBot.loop.create_task(check_expired_premium(JisshuBot))
    logging.info(
        f"{me.first_name} with for Pyrogram v{__version__} (Layer {layer}) started on {me.username}."
    )
    logging.info(script.LOGO)
    tz = pytz.timezone("Asia/Kolkata")
    today = date.today()
    now = datetime.now(tz)
    time = now.strftime("%H:%M:%S %p")

    # --- SAFELY send restart messages to LOG_CHANNEL and SUPPORT_GROUP (these are single messages)
    try:
        await JisshuBot.send_message(chat_id=LOG_CHANNEL, text=script.RESTART_TXT.format(me.mention, today, time))
    except Exception:
        logging.exception("Failed to send restart to LOG_CHANNEL")

    try:
        await JisshuBot.send_message(chat_id=SUPPORT_GROUP, text=f"<b>{me.mention} ʀᴇsᴛᴀʀᴛᴇᴅ 🤖</b>")
    except Exception:
        logging.exception("Failed to send restart to SUPPORT_GROUP")

    # --- Non-blocking: send restart notice to all users (wrap in task to avoid blocking startup)
    try:
        asyncio.create_task(send_restart_notice_to_all())
    except Exception:
        logging.exception("Failed to schedule send_restart_notice_to_all")

    # Setup web server (use env PORT if provided by platform like Koyeb)
    # If plugins.web_server() already adds a root "/" route, this will still work.
    try:
        app = await web_server()
        # ensure root exists for health check
        if not any(getattr(r.resource, "canonical", None) == "/" for r in app.router.routes()):
            app.router.add_get("/", _root_health)
        runner = web.AppRunner(app)
        await runner.setup()
        bind_address = "0.0.0.0"
        port = int(os.getenv("PORT", 8080))
        site = web.TCPSite(runner, bind_address, port)
        await site.start()
        logging.info("Web server started on %s:%s", bind_address, port)
    except Exception as e:
        logging.exception("Failed to start web server: %s", e)

    await idle()

# ---------------------------
# run main
# ---------------------------
if __name__ == "__main__":
    try:
        loop.run_until_complete(Jisshu_start())
    except KeyboardInterrupt:
        logging.info("Service Stopped Bye 👋")
