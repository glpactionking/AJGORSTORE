import sqlite3
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters

# --- LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION (Use environment variables!) ---
# Terminal mein set karo: export BOT_TOKEN="your_token_here"
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8658966276:AAGpUJpg54hUu7-8I1tUE1dDNTMaePiRobM")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8013912448"))
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "@AJGOROP")

# Conversation state for deposit amount
WAITING_DEPOSIT_AMOUNT = 1

# --- DATABASE SETUP ---
def init_db():
    with sqlite3.connect('shop_bot.db', timeout=30) as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                         (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0, currency TEXT DEFAULT 'BDT')''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS keys 
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, key_value TEXT UNIQUE, price REAL, duration TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS orders 
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, key_value TEXT, 
                          price REAL, duration TEXT, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

        # Safe column migration
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'currency' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN currency TEXT DEFAULT 'BDT'")
        conn.commit()

def get_balance(user_id):
    """Get user balance from DB."""
    with sqlite3.connect('shop_bot.db', timeout=30) as conn:
        data = conn.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
        return data[0] if data else 0

def ensure_user_exists(user_id):
    """Insert user if not already in DB."""
    with sqlite3.connect('shop_bot.db', timeout=30) as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()

# --- MAIN COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ensure_user_exists(user_id)

    balance = get_balance(user_id)
    text = f"👋 Hello {update.effective_user.first_name}!\n\n💰 *Your Balance:* ৳{balance}\n🌍 *Currency:* BDT ৳"
    keyboard = [
        [InlineKeyboardButton("🛒 Buy Key", callback_data='buy_menu')],
        [InlineKeyboardButton("💰 Wallet", callback_data='wallet'),
         InlineKeyboardButton("📜 History", callback_data='history')]
    ]
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🛠 Admin Panel", callback_data='admin_panel')])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# --- ADMIN FUNCTIONS ---
async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    with sqlite3.connect('shop_bot.db', timeout=30) as conn:
        users = conn.execute("SELECT user_id, balance FROM users").fetchall()

    if not users:
        await update.message.reply_text("No users found.")
        return

    # Pagination: 30 users per message to avoid Telegram 4096 char limit
    chunk_size = 30
    for i in range(0, len(users), chunk_size):
        chunk = users[i:i + chunk_size]
        msg = f"👥 *User List ({i+1}-{i+len(chunk)} of {len(users)}):*\n\n"
        for u, b in chunk:
            msg += f"ID: `{u}` | Bal: ৳{b}\n"
        await update.message.reply_text(msg, parse_mode='Markdown')

async def add_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid, amt = int(context.args[0]), float(context.args[1])
        with sqlite3.connect('shop_bot.db', timeout=30) as conn:
            result = conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, uid))
            conn.commit()
            if result.rowcount == 0:
                await update.message.reply_text("❌ User not found.")
                return
        await update.message.reply_text(f"✅ ৳{amt} added to `{uid}`.", parse_mode='Markdown')
        # FIX: Added parse_mode='Markdown' here
        await context.bot.send_message(uid, f"💰 *Wallet Updated!*\n\n৳{amt} aapke account mein add ho gaya!\nNew Balance: ৳{get_balance(uid)}", parse_mode='Markdown')
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: `/addmoney ID AMT`", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"add_money error: {e}")
        await update.message.reply_text("❌ Error occurred.")

async def add_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        p, dur, k = float(context.args[0]), context.args[1].replace("_", " "), context.args[2]
        with sqlite3.connect('shop_bot.db', timeout=30) as conn:
            conn.execute("INSERT INTO keys (key_value, price, duration) VALUES (?,?,?)", (k, p, dur))
            conn.commit()
        await update.message.reply_text(f"✅ Key Added: `{k}`", parse_mode='Markdown')
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: `/addkey 500 1_Day KEY`", parse_mode='Markdown')
    except sqlite3.IntegrityError:
        await update.message.reply_text("❌ Key already exists.")
    except Exception as e:
        logger.error(f"add_key error: {e}")
        await update.message.reply_text("❌ Error occurred.")

async def bulk_add_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        p, dur = float(context.args[0]), context.args[1].replace("_", " ")
        keys = " ".join(context.args[2:]).split(",")
        added, skipped = 0, 0
        with sqlite3.connect('shop_bot.db', timeout=30) as conn:
            for k in keys:
                k = k.strip()
                if k:
                    try:
                        conn.execute("INSERT INTO keys (key_value, price, duration) VALUES (?,?,?)", (k, p, dur))
                        added += 1
                    except sqlite3.IntegrityError:
                        skipped += 1  # Duplicate key
            conn.commit()
        await update.message.reply_text(f"✅ {added} keys added. {skipped} duplicates skipped.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: `/bulkkey 500 1_Day K1,K2,K3`", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"bulk_add_keys error: {e}")
        await update.message.reply_text("❌ Error occurred.")

async def remove_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        k = context.args[0]
        with sqlite3.connect('shop_bot.db', timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM keys WHERE key_value = ?", (k,))
            conn.commit()
            status = "✅ Key removed." if cursor.rowcount > 0 else "❌ Key not found."
        await update.message.reply_text(status)
    except IndexError:
        await update.message.reply_text("Usage: `/removekey KEY`", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"remove_key error: {e}")
        await update.message.reply_text("❌ Error occurred.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("Usage: `/broadcast Your message here`", parse_mode='Markdown')
        return
    with sqlite3.connect('shop_bot.db', timeout=30) as conn:
        users = conn.execute("SELECT user_id FROM users").fetchall()
    sent, failed = 0, 0
    for (uid,) in users:
        try:
            await context.bot.send_message(uid, f"📢 *Notice:*\n\n{msg}", parse_mode='Markdown')
            sent += 1
        except Exception as e:
            logger.warning(f"Broadcast failed for {uid}: {e}")
            failed += 1
    await update.message.reply_text(f"✅ Broadcast done.\n✅ Sent: {sent} | ❌ Failed: {failed}")

# --- DEPOSIT CONVERSATION ---
async def deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask user for deposit amount."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💰 *Deposit Request*\n\nAap kitna deposit karna chahte hain?\n\nSirf amount type karein (e.g. `500`)",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='wallet')]])
    )
    return WAITING_DEPOSIT_AMOUNT

async def deposit_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive deposit amount from user."""
    user_id = update.effective_user.id
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError("Amount must be positive")
        # Notify admin with correct amount
        await context.bot.send_message(
            ADMIN_ID,
            f"💰 *Deposit Request!*\n\nUser ID: `{user_id}`\nAmount: ৳{amount}\n\nApprove karne ke liye:\n`/addmoney {user_id} {amount}`",
            parse_mode='Markdown'
        )
        await update.message.reply_text(
            f"✅ *Deposit request bhej diya!*\n\nAmount: ৳{amount}\n\nAdmin {OWNER_USERNAME} ko screenshot bhi bhejein payment ka.",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Sirf number enter karein jaise `500`", parse_mode='Markdown')
    return ConversationHandler.END

async def deposit_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

# --- CALLBACK HANDLER ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data == 'main_menu':
        bal = get_balance(user_id)
        text = f"👋 Hello {query.from_user.first_name}!\n💰 *Balance:* ৳{bal}\n🌍 *Currency:* BDT ৳"
        btns = [
            [InlineKeyboardButton("🛒 Buy Key", callback_data='buy_menu')],
            [InlineKeyboardButton("💰 Wallet", callback_data='wallet'),
             InlineKeyboardButton("📜 History", callback_data='history')]
        ]
        if user_id == ADMIN_ID:
            btns.append([InlineKeyboardButton("🛠 Admin Panel", callback_data='admin_panel')])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(btns), parse_mode='Markdown')

    elif data == 'buy_menu':
        with sqlite3.connect('shop_bot.db', timeout=30) as conn:
            products = conn.execute(
                "SELECT duration, price, MIN(id) FROM keys GROUP BY duration, price"
            ).fetchall()
        msg = "🎮 🛒 *Drip Client ApkMod*\n" + "—" * 15 + "\n\n"
        btns = []
        if not products:
            msg += "❌ *Stock is empty.*"
        else:
            for dur, prc, key_id in products:
                with sqlite3.connect('shop_bot.db', timeout=30) as conn:
                    stock = conn.execute(
                        "SELECT COUNT(id) FROM keys WHERE duration=? AND price=?", (dur, prc)
                    ).fetchone()[0]
                msg += f"⏱ *{dur}*\n💰 Price: ৳{prc}\n📦 Stock: {stock}\n\n"
                if stock > 0:
                    btns.append([InlineKeyboardButton(f"🛒 Buy {dur} - ৳{prc}", callback_data=f"b:{key_id}")])
        btns.append([InlineKeyboardButton("🔙 Back", callback_data='main_menu')])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(btns), parse_mode='Markdown')

    elif data.startswith('b:'):
        key_id = int(data.split(':')[1])
        bal = get_balance(user_id)

        # FIX: Use SELECT FOR UPDATE equivalent — lock with rowid check inside transaction
        with sqlite3.connect('shop_bot.db', timeout=30, isolation_level='EXCLUSIVE') as conn:
            cursor = conn.cursor()
            # Re-fetch item inside the transaction to prevent race condition
            item = cursor.execute(
                "SELECT key_value, price, duration FROM keys WHERE id=?", (key_id,)
            ).fetchone()

            if not item:
                await query.edit_message_text(
                    "❌ Yeh key already sold out ho gayi!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='buy_menu')]])
                )
                return

            if bal < item[1]:
                await query.edit_message_text(
                    f"❌ *Low Balance!*\nChahiye: ৳{item[1]}\nAapke paas: ৳{bal}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='buy_menu')]]),
                    parse_mode='Markdown'
                )
                return

            try:
                cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (item[1], user_id))
                cursor.execute("DELETE FROM keys WHERE id = ?", (key_id,))
                cursor.execute(
                    "INSERT INTO orders (user_id, key_value, price, duration) VALUES (?,?,?,?)",
                    (user_id, item[0], item[1], item[2])
                )
                conn.commit()
                new_bal = get_balance(user_id)
                await query.edit_message_text(
                    f"✅ *Purchase Successful!*\n\n🔑 Key: `{item[0]}`\n⏱ Duration: {item[2]}\n💰 Spent: ৳{item[1]}\n💳 Remaining Balance: ৳{new_bal}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='main_menu')]]),
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Purchase error for user {user_id}: {e}")
                conn.rollback()
                await query.edit_message_text("❌ Database Error! Dobara try karein.")

    elif data == 'wallet':
        bal = get_balance(user_id)
        text = (
            f"💳 *Wallet*\n\n"
            f"👤 ID: `{user_id}`\n"
            f"💰 Balance: ৳{bal}\n\n"
            f"Deposit ke liye Admin {OWNER_USERNAME} ko payment karein aur screenshot bhejein."
        )
        btns = [
            [InlineKeyboardButton("➕ Request Deposit", callback_data='req_dep')],
            [InlineKeyboardButton("🔙 Back", callback_data='main_menu')]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(btns), parse_mode='Markdown')

    elif data == 'history':
        with sqlite3.connect('shop_bot.db', timeout=30) as conn:
            orders = conn.execute(
                "SELECT key_value, price, duration, date FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 5",
                (user_id,)
            ).fetchall()
        msg = "📜 *Purchase History (Last 5):*\n\n"
        if not orders:
            msg = "❌ Koi history nahi mili."
        else:
            for k, p, d, dt in orders:
                msg += f"⏱ {d} | ৳{p}\n🔑 `{k}`\n📅 {str(dt)[:16]}\n\n"
        await query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='main_menu')]]),
            parse_mode='Markdown'
        )

    elif data == 'admin_panel' and user_id == ADMIN_ID:
        await query.edit_message_text(
            "🛠 *Admin Panel*\n\n"
            "📋 *Commands:*\n"
            "`/users` — Sab users dekho\n"
            "`/addmoney ID AMT` — Balance add karo\n"
            "`/addkey PRICE DUR KEY` — Ek key add karo\n"
            "`/bulkkey PRICE DUR K1,K2` — Bulk keys add karo\n"
            "`/removekey KEY` — Key hatao\n"
            "`/broadcast MSG` — Sab ko message bhejo",
            parse_mode='Markdown'
        )

# --- RUN BOT ---
if __name__ == '__main__':
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("⚠️  ERROR: BOT_TOKEN set nahi hai!")
        print("Terminal mein run karo: export BOT_TOKEN='your_actual_token'")
        exit(1)

    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Deposit conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(deposit_start, pattern='^req_dep$')],
        states={
            WAITING_DEPOSIT_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amount_received)
            ],
        },
        fallbacks=[CallbackQueryHandler(deposit_cancel, pattern='^wallet$')],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addmoney", add_money))
    app.add_handler(CommandHandler("bulkkey", bulk_add_keys))
    app.add_handler(CommandHandler("addkey", add_key))
    app.add_handler(CommandHandler("removekey", remove_key))
    app.add_handler(CommandHandler("users", list_users))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("✅ Bot is Ready!")
    app.run_polling()
    