import os
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
cred = credentials.Certificate("../service-account.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# ── Config ────────────────────────────────────────────────
BOT_TOKEN      = "8200530338:AAGfM7zyPRINlKvukhGesYLcInQjAKpH6xg"          # 🔁 BotFather se lo
ADMIN_IDS      = [1747637476]               # 🔁 apna Telegram ID
CHANNEL_ID     = "@missiontopper_freebatches"           # 🔁 e.g. "@missiontopper" (public) or -100xxxxxxx (private)
KEY_EXPIRY_HOURS = 24

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

def save_key_to_firebase(key: str, created_by: int) -> int:
    expires_at = int((datetime.now() + timedelta(hours=KEY_EXPIRY_HOURS)).timestamp() * 1000)
    db.collection("keys").document(key).set({
        "used": False,
        "usedBy": None,
        "createdAt": int(time.time() * 1000),
        "expiresAt": expires_at,
        "createdBy": created_by,
    })
    return expires_at

# ── /start ────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"👋 Hello *{user.first_name}*!\n\n"
        "🎓 *Mission Topper Bot*\n\n"
        "📌 Commands:\n"
        "• /getkey — Get your access key\n"
        "• /mykey — Check your key status\n"
    )
    if is_admin(user.id):
        text += (
            "\n🔐 *Admin Commands:*\n"
            "• /genkey [count] — Generate key(s)\n"
            "• /deletekey KEY — Delete a key\n"
            "• /listkeys — List recent keys\n"
            "• /listusers — List users\n"
            "• /ban UID — Ban user\n"
            "• /unban UID — Unban user\n"
            "• /stats — App statistics\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown")

# ── /getkey — for everyone, requires channel join ─────────
async def getkey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Check channel membership
    joined = await is_member(ctx.bot, user.id)
    if not joined:
        keyboard = [[
            InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"),
            InlineKeyboardButton("✅ I Joined", callback_data="check_join"),
        ]]
        await update.message.reply_text(
            "⚠️ *Join our channel first to get a key!*\n\n"
            f"👉 Join: {CHANNEL_ID}\n\n"
            "After joining, click *I Joined* below.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    await _send_key(update, ctx, user.id)

# ── Callback: "I Joined" button ───────────────────────────
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if query.data == "check_join":
        joined = await is_member(ctx.bot, user.id)
        if not joined:
            await query.message.reply_text(
                "❌ You haven't joined yet!\n\n"
                f"Please join {CHANNEL_ID} and try again.",
            )
            return
        await _send_key(query, ctx, user.id)

    elif query.data == "gen_key_admin":
        if not is_admin(user.id): return
        ctx.args = ["1"]
        await genkey(query, ctx)

# ── Internal: generate + send key ─────────────────────────
async def _send_key(update, ctx, user_id: int):
    key = gen_key()
    expires_at = save_key_to_firebase(key, user_id)
    expires_str = datetime.fromtimestamp(expires_at / 1000).strftime("%d %b %Y %H:%M")

    msg = (
        f"🎉 *Your Access Key*\n\n"
        f"`{key}`\n\n"
        f"⏰ Valid for *{KEY_EXPIRY_HOURS} hours*\n"
        f"📅 Expires: {expires_str}\n\n"
        f"📱 Enter this key in the app to get access."
    )

    # reply_text works for both Message and CallbackQuery
    if hasattr(update, "message") and update.message:
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")

# ── /genkey [count] — ADMIN ONLY, no channel check ────────
async def genkey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user if hasattr(update, "effective_user") else update.from_user
    if not is_admin(user.id):
        target = update.message if hasattr(update, "message") else update
        await target.reply_text("❌ Not authorized.")
        return

    count = 1
    if ctx.args:
        try:
            count = min(int(ctx.args[0]), 50)
        except ValueError:
            pass

    keys = []
    batch = db.batch()
    expires_at = int((datetime.now() + timedelta(hours=KEY_EXPIRY_HOURS)).timestamp() * 1000)

    for _ in range(count):
        key = gen_key()
        ref = db.collection("keys").document(key)
        batch.set(ref, {
            "used": False,
            "usedBy": None,
            "createdAt": int(time.time() * 1000),
            "expiresAt": expires_at,
            "createdBy": user.id,
        })
        keys.append(key)

    batch.commit()
    expires_str = datetime.fromtimestamp(expires_at / 1000).strftime("%d %b %Y %H:%M")
    key_text = "\n".join([f"`{k}`" for k in keys])

    msg = (
        f"✅ *{count} Key(s) Generated*\n\n"
        f"{key_text}\n\n"
        f"⏰ Expires: {expires_str}"
    )

    target = update.message if hasattr(update, "message") and update.message else update
    await target.reply_text(msg, parse_mode="Markdown")

# ── /deletekey <key> ──────────────────────────────────────
async def deletekey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /deletekey KEY")
        return

    key = ctx.args[0].upper()
    snap = db.collection("keys").document(key).get()
    if not snap.exists:
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
        if d.get("used"):
            status = "✅ Used"
        elif now_ms > d.get("expiresAt", 0):
            status = "⏰ Expired"
        else:
            status = "� Available"
        lines.append(f"`{s.id}` — {status}")

    await update.message.reply_text(
        "� *Recent Keys (last 20)*\n\n" + "\n".join(lines),
        parse_mode="Markdown"
    )

# ── /mykey ────────────────────────────────────────────────
async def mykey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tg_id = str(update.effective_user.id)
    users = db.collection("users").where("telegramId", "==", tg_id).limit(1).get()

    if not users:
        await update.message.reply_text(
            "❌ Account not linked.\nLogin in the app first."
        )
        return

    user_data = users[0].to_dict()
    key_used = user_data.get("keyUsed")
    if not key_used:
        await update.message.reply_text("🔑 No key used yet.")
        return

    snap = db.collection("keys").document(key_used).get()
    if snap.exists:
        kd = snap.to_dict()
        expires = datetime.fromtimestamp(kd["expiresAt"] / 1000).strftime("%d %b %Y %H:%M")
        await update.message.reply_text(
            f"🔑 Key: `{key_used}`\n⏰ Expires: {expires}",
            parse_mode="Markdown"
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
        "👥 *Users (last 20)*\n\n" + "\n".join(lines),
        parse_mode="Markdown"
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
    await update.message.reply_text(f"🚫 User `{ctx.args[0]}` banned.", parse_mode="Markdown")

async def unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /unban <uid>")
        return
    db.collection("users").document(ctx.args[0]).update({"blocked": False})
    await update.message.reply_text(f"✅ User `{ctx.args[0]}` unbanned.", parse_mode="Markdown")

# ── /stats ────────────────────────────────────────────────
async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return

    all_users = db.collection("users").get()
    all_keys  = db.collection("keys").get()
    used_keys = [k for k in all_keys if k.to_dict().get("used")]

    await update.message.reply_text(
        f"📊 *Stats*\n\n"
        f"👥 Users: {len(all_users)}\n"
        f"🔑 Total Keys: {len(all_keys)}\n"
        f"✅ Used: {len(used_keys)}\n"
        f"🟢 Available: {len(all_keys) - len(used_keys)}",
        parse_mode="Markdown"
    )

# ── Main ──────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("getkey",     getkey))   # everyone
    app.add_handler(CommandHandler("genkey",     genkey))   # admin only
    app.add_handler(CommandHandler("deletekey",  deletekey))
    app.add_handler(CommandHandler("listkeys",   listkeys))
    app.add_handler(CommandHandler("mykey",      mykey))
    app.add_handler(CommandHandler("listusers",  listusers))
    app.add_handler(CommandHandler("ban",        ban))
    app.add_handler(CommandHandler("unban",      unban))
    app.add_handler(CommandHandler("stats",      stats))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
