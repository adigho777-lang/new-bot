import os
import json
import time
import random
import string
from datetime import datetime, timedelta

import firebase_admin
from firebase_admin import credentials, firestore
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

# ── Firebase Init ─────────────────────────────────────────
# Option 1: service-account.json file (local)
# Option 2: FIREBASE_CREDENTIALS env var (production/container)
if os.path.exists("service-account.json"):
    cred = credentials.Certificate("service-account.json")
elif os.path.exists("../service-account.json"):
    cred = credentials.Certificate("../service-account.json")
else:
    # Load from environment variable (Railway/Render/VPS)
    sa_json = os.environ.get("FIREBASE_CREDENTIALS")
    if not sa_json:
        raise RuntimeError("No Firebase credentials found! Set FIREBASE_CREDENTIALS env var.")
    cred = credentials.Certificate(json.loads(sa_json))

firebase_admin.initialize_app(cred)
db = firestore.client()

# ── Config from env or hardcode ───────────────────────────
BOT_TOKEN        = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_IDS        = list(map(int, os.environ.get("ADMIN_IDS", "123456789").split(",")))
CHANNEL_ID       = os.environ.get("CHANNEL_ID", "@your_channel")
KEY_EXPIRY_HOURS = int(os.environ.get("KEY_EXPIRY_HOURS", "24"))

# ── Helpers ───────────────────────────────────────────────
def gen_key(length=12):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

async def is_member(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in [
            ChatMember.MEMBER,
            ChatMember.ADMINISTRATOR,
            ChatMember.OWNER,
        ]
    except Exception:
        return False

def save_key(key: str, created_by: int) -> int:
    expires_at = int((datetime.now() + timedelta(hours=KEY_EXPIRY_HOURS)).timestamp() * 1000)
    db.collection("keys").document(key).set({
        "used": False,
        "usedBy": None,
        "createdAt": int(time.time() * 1000),
        "expiresAt": expires_at,
        "createdBy": created_by,
    })
    return expires_at

async def send_key_msg(message, key: str, expires_at: int):
    expires_str = datetime.fromtimestamp(expires_at / 1000).strftime("%d %b %Y %H:%M")
    await message.reply_text(
        f"🎉 *Your Access Key*\n\n"
        f"`{key}`\n\n"
        f"⏰ Valid for *{KEY_EXPIRY_HOURS} hours*\n"
        f"📅 Expires: {expires_str}\n\n"
        f"📱 Enter this key in the app to get access.",
        parse_mode="Markdown"
    )

# ── /start ────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"👋 Hello *{user.first_name}*!\n\n"
        "🎓 *Mission Topper Bot*\n\n"
        "📌 Commands:\n"
        "• /getkey — Get your free access key\n"
        "• /mykey — Check your key status\n"
    )
    if is_admin(user.id):
        text += (
            "\n� *Admin Commands:*\n"
            "• /genkey [count] — Generate key(s) instantly\n"
            "• /deletekey KEY — Delete a key\n"
            "• /listkeys — List recent keys\n"
            "• /listusers — List users\n"
            "• /ban UID — Ban user\n"
            "• /unban UID — Unban user\n"
            "• /stats — App statistics\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown")

# ── /getkey — everyone, requires channel join ─────────────
async def getkey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    joined = await is_member(ctx.bot, user.id)
    if not joined:
        channel_username = CHANNEL_ID.lstrip("@")
        keyboard = [[
            InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{channel_username}"),
            InlineKeyboardButton("✅ I Joined", callback_data="check_join"),
        ]]
        await update.message.reply_text(
            f"⚠️ *Join our channel first!*\n\n"
            f"👉 {CHANNEL_ID}\n\n"
            "After joining tap *I Joined* ✅",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    key = gen_key()
    expires_at = save_key(key, user.id)
    await send_key_msg(update.message, key, expires_at)

# ── Callback: "I Joined" button ───────────────────────────
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if query.data == "check_join":
        joined = await is_member(ctx.bot, user.id)
        if not joined:
            channel_username = CHANNEL_ID.lstrip("@")
            keyboard = [[
                InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{channel_username}"),
                InlineKeyboardButton("✅ I Joined", callback_data="check_join"),
            ]]
            await query.message.reply_text(
                "❌ *Still not joined!*\n\nPlease join the channel first.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        key = gen_key()
        expires_at = save_key(key, user.id)
        await send_key_msg(query.message, key, expires_at)

# ── /genkey [count] — ADMIN ONLY, no channel check ────────
async def genkey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return

    count = 1
    if ctx.args:
        try:
            count = min(int(ctx.args[0]), 50)
        except ValueError:
            pass

    expires_at = int((datetime.now() + timedelta(hours=KEY_EXPIRY_HOURS)).timestamp() * 1000)
    batch = db.batch()
    keys = []

    for _ in range(count):
        key = gen_key()
        ref = db.collection("keys").document(key)
        batch.set(ref, {
            "used": False,
            "usedBy": None,
            "createdAt": int(time.time() * 1000),
            "expiresAt": expires_at,
            "createdBy": update.effective_user.id,
        })
        keys.append(key)

    batch.commit()
    expires_str = datetime.fromtimestamp(expires_at / 1000).strftime("%d %b %Y %H:%M")
    key_text = "\n".join([f"`{k}`" for k in keys])

    await update.message.reply_text(
        f"✅ *{count} Key(s) Generated*\n\n{key_text}\n\n⏰ Expires: {expires_str}",
        parse_mode="Markdown"
    )

# ── /deletekey <key> ──────────────────────────────────────
async def deletekey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /deletekey KEY")
        return

    key = ctx.args[0].upper()
    if not db.collection("keys").document(key).get().exists:
        await update.message.reply_text("❌ Key not found.")
        return

    db.collection("keys").document(key).delete()
    await update.message.reply_text(f"🗑️ Key `{key}` deleted.", parse_mode="Markdown")

# ── /listkeys ─────────────────────────────────────────────
async def listkeys(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return

    snaps = db.collection("keys").order_by("createdAt", direction=firestore.Query.DESCENDING).limit(20).get()
    if not snaps:
        await update.message.reply_text("No keys found.")
        return

    now_ms = int(time.time() * 1000)
    lines = []
    for s in snaps:
        d = s.to_dict()
        if d.get("used"):       status = "✅ Used"
        elif now_ms > d.get("expiresAt", 0): status = "⏰ Expired"
        else:                   status = "🟢 Available"
        lines.append(f"`{s.id}` — {status}")

    await update.message.reply_text(
        "📋 *Recent Keys (last 20)*\n\n" + "\n".join(lines),
        parse_mode="Markdown"
    )

# ── /mykey ────────────────────────────────────────────────
async def mykey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tg_id = str(update.effective_user.id)
    users = db.collection("users").where("telegramId", "==", tg_id).limit(1).get()

    if not users:
        await update.message.reply_text("❌ Account not linked. Login in the app first.")
        return

    key_used = users[0].to_dict().get("keyUsed")
    if not key_used:
        await update.message.reply_text("🔑 No key used yet.")
        return

    snap = db.collection("keys").document(key_used).get()
    if snap.exists:
        expires = datetime.fromtimestamp(snap.to_dict()["expiresAt"] / 1000).strftime("%d %b %Y %H:%M")
        await update.message.reply_text(
            f"🔑 Key: `{key_used}`\n⏰ Expires: {expires}", parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"🔑 Key: `{key_used}`", parse_mode="Markdown")

# ── /listusers ────────────────────────────────────────────
async def listusers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return

    snaps = db.collection("users").limit(20).get()
    if not snaps:
        await update.message.reply_text("No users found.")
        return

    lines = []
    for s in snaps:
        d = s.to_dict()
        icon = "🚫" if d.get("blocked") else "✅"
        lines.append(f"{icon} {d.get('name', 'Unknown')} — `{s.id[:10]}...`")

    await update.message.reply_text(
        "👥 *Users (last 20)*\n\n" + "\n".join(lines), parse_mode="Markdown"
    )

# ── /ban + /unban ─────────────────────────────────────────
async def ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /ban <uid>")
        return
    db.collection("users").document(ctx.args[0]).update({"blocked": True})
    await update.message.reply_text(f"🚫 `{ctx.args[0]}` banned.", parse_mode="Markdown")

async def unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /unban <uid>")
        return
    db.collection("users").document(ctx.args[0]).update({"blocked": False})
    await update.message.reply_text(f"✅ `{ctx.args[0]}` unbanned.", parse_mode="Markdown")

# ── /stats ────────────────────────────────────────────────
async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return

    all_users = db.collection("users").get()
    all_keys  = db.collection("keys").get()
    used      = [k for k in all_keys if k.to_dict().get("used")]

    await update.message.reply_text(
        f"📊 *Stats*\n\n"
        f"👥 Users: {len(all_users)}\n"
        f"🔑 Total Keys: {len(all_keys)}\n"
        f"✅ Used: {len(used)}\n"
        f"🟢 Available: {len(all_keys) - len(used)}",
        parse_mode="Markdown"
    )

# ── Main ──────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("getkey",    getkey))
    app.add_handler(CommandHandler("genkey",    genkey))
    app.add_handler(CommandHandler("deletekey", deletekey))
    app.add_handler(CommandHandler("listkeys",  listkeys))
    app.add_handler(CommandHandler("mykey",     mykey))
    app.add_handler(CommandHandler("listusers", listusers))
    app.add_handler(CommandHandler("ban",       ban))
    app.add_handler(CommandHandler("unban",     unban))
    app.add_handler(CommandHandler("stats",     stats))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
