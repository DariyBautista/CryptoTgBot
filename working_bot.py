import os, json, asyncio, aiohttp
from typing import Optional
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters, CallbackContext
)
import re 

# ──────────────────────────────────────────
TELEGRAM_TOKEN = "7979794571:AAGlfGoQq-dmECouLPq_5qrlRLJCknuZBdU"
CMC_API_KEY    = "29fc8a16-d00d-4317-87b8-b772efa562dc"
USER_DATA_FILE = "user_data.json"
# ──────────────────────────────────────────

# Структура: {uid:int: {symbol:str: {"track": int|None, "last": float|None}}}
user_fav: dict[int, dict[str, dict]] = {}

# ────────── файл I/O ─────────
def load_data():
    global user_fav
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                user_fav = {int(k): v for k, v in raw.items()}
        except json.JSONDecodeError:
            user_fav = {}
    else:
        user_fav = {}

def save_data():
    with open(USER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in user_fav.items()}, f, ensure_ascii=False, indent=2)

# ────── клавіатури ───────
def main_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("➕ Додати токен", callback_data="add")],
        [InlineKeyboardButton("📈 Поточні курси", callback_data="prices")],
        [InlineKeyboardButton("❌ Видалити токен", callback_data="del")],
    ]
    return InlineKeyboardMarkup(kb)

def alert_kb(symbol: str) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("5 %",  callback_data=f"alert_{symbol}_5"),
         InlineKeyboardButton("10 %", callback_data=f"alert_{symbol}_10"),
         InlineKeyboardButton("25 %", callback_data=f"alert_{symbol}_25")],
        [InlineKeyboardButton("🚫 Не слідкувати", callback_data=f"alert_{symbol}_off")]
    ]
    return InlineKeyboardMarkup(kb)

# ────── /start ──────
async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Обери дію:", reply_markup=main_kb())

# ────── текстові повідомлення ──────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.message.from_user.id
    text = update.message.text.strip()

    # 1️⃣  Чекаємо на введення токена для списку «улюблених»
    if context.user_data.get("await_token"):
        context.user_data["await_token"] = False
        sym = text.upper()
        user_fav.setdefault(uid, {})[sym] = {"track": None, "last": None}
        save_data()
        await update.message.reply_text(
            f"✅ {sym} додано.\nВибери поріг сповіщення:",
            reply_markup=alert_kb(sym)
        )
        return

    # 2️⃣  Перевіряємо шаблон «<число> <символ>»
    m = re.fullmatch(r"\s*([\d.]+)\s+([a-zA-Z0-9]+)\s*", text)
    if m:
        qty, sym = float(m.group(1)), m.group(2).upper()
        price = await get_price_float(sym)
        if price is None:
            await update.message.reply_text(f"Не вдалося знайти ціну для {sym}.")
        else:
            total = qty * price
            await update.message.reply_text(
                f"{qty:g} {sym} ≈ **${total:,.2f}**",
                parse_mode="Markdown"
            )
        return

    # 3️⃣  Інші випадки → показуємо клавіатуру
    await update.message.reply_text("Натисни кнопку ↓", reply_markup=main_kb())

# ────── callback-кнопки ──────
async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "add":
        context.user_data["await_token"] = True
        await q.edit_message_text("Введи символ токена (BTC) або адресу контракту:")
    elif q.data == "prices":
        await send_prices(q)
    elif q.data == "del":
        await show_del_menu(q)
    elif q.data.startswith("delete_"):
        sym = q.data.replace("delete_", "")
        user_fav.get(uid, {}).pop(sym, None)
        save_data()
        await q.edit_message_text(f"🗑 {sym} видалено.", reply_markup=main_kb())
    elif q.data.startswith("alert_"):
        _, sym, val = q.data.split("_")
        if val == "off":
            user_fav[uid][sym]["track"] = None
            msg = f"🔕 Сповіщення {sym} вимкнено."
        else:
            user_fav[uid][sym]["track"] = int(val)
            msg = f"🔔 {sym}: сповіщення при ±{val}%."
        save_data()
        await q.edit_message_text(msg, reply_markup=main_kb())
    elif q.data == "back":
        await q.edit_message_text("👋 Обери дію:", reply_markup=main_kb())

# ────── меню видалення ──────
async def show_del_menu(q):
    uid = q.from_user.id
    toks = list(user_fav.get(uid, {}))
    if not toks:
        await q.edit_message_text("Список порожній.", reply_markup=main_kb()); return
    kb = [[InlineKeyboardButton(t, callback_data=f"delete_{t}")] for t in toks]
    kb.append([InlineKeyboardButton("↩ Назад", callback_data="back")])
    await q.edit_message_text("Оберіть токен для видалення:", reply_markup=InlineKeyboardMarkup(kb))

# ────── показ цін ──────
async def send_prices(q):
    uid = q.from_user.id
    toks = user_fav.get(uid, {})
    if not toks:
        await q.edit_message_text("Немає улюблених токенів.", reply_markup=main_kb()); return
    lines = []
    for s in toks:
        p = await get_price(s)
        lines.append(f"{s}: {p}")
    kb = [[InlineKeyboardButton("↩ Назад", callback_data="back")]]
    await q.edit_message_text("📊 Поточні курси:\n\n" + "\n".join(lines),
                              reply_markup=InlineKeyboardMarkup(kb))

# ────── запит до CMC ──────
async def get_price(symbol: str) -> str:
    p = await get_price_float(symbol)
    return "❌" if p is None else f"${p:,.2f}"

async def get_price_float(symbol: str) -> Optional[float]:
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    params  = {"symbol": symbol.upper(), "convert": "USD"}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=headers, params=params) as r:
            if r.status != 200: return None
            data = await r.json()
            try:
                return data["data"][symbol.upper()]["quote"]["USD"]["price"]
            except KeyError:
                return None

# ────── фоновий монітор ──────
async def watcher(ctx: CallbackContext):
    for uid, toks in user_fav.items():
        for sym, cfg in toks.items():
            trig = cfg.get("track")
            if not trig:                       # 0 / None → не стежимо
                continue
            price = await get_price_float(sym)
            if price is None: continue

            last = cfg.get("last")
            if last is None:
                cfg["last"] = price
                continue

            diff = (price - last) / last * 100
            if abs(diff) >= trig:
                sign = "📈" if diff > 0 else "📉"
                text = (f"{sign} {sym} змінився на {diff:+.2f}%\n"
                        f"Нова ціна: ${price:,.2f}")
                try:
                    await ctx.bot.send_message(uid, text)
                except Exception:
                    pass
                cfg["last"] = price
                save_data()

# ────── запуск ──────
async def main():
    load_data()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # фоновий джоб кожні 5 хв
    app.job_queue.run_repeating(watcher, interval=300, first=10)

    print("✅ Бот запущено…")
    await app.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.get_event_loop().run_until_complete(main())