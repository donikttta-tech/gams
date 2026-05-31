import asyncio
import random
import json
import os
import html
from datetime import date, datetime
from aiohttp import ClientSession

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ─── CONFIG ─────────────────────────────────────────────────────────────────
TOKEN = "8906467127:AAEXNVFAzDfR95fZwT7Fyn4wLEeRtKU5sL4"
DB_FILE = "users.json"
PROMO_FILE = "promos.json"
ADMIN_ID = "8144110555"

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ─── RAW TG API (цветные кнопки, premium emoji) ─────────────────────────────
_http = None

async def tg(method, **kw):
    global _http
    if _http is None or _http.closed:
        _http = ClientSession()
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    async with _http.post(url, json=kw) as r:
        return await r.json()

async def send_msg(chat_id, text, reply_markup=None):
    p = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup: p["reply_markup"] = reply_markup
    return await tg("sendMessage", **p)

async def edit_msg(chat_id, msg_id, text, reply_markup=None):
    p = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "message_id": msg_id}
    if reply_markup: p["reply_markup"] = reply_markup
    try:
        return await tg("editMessageText", **p)
    except Exception:
        return None

# ─── PREMIUM EMOJI ──────────────────────────────────────────────────────────
EI_OK   = "5310076249404621168"
EI_LIKE = "5285430309720966085"
EI_WARN = "5310169226856644648"
EI_STAR = "5285032475490273112"

def ae(emoji, eid):
    return f'<tg-emoji emoji-id="{eid}">{emoji}</tg-emoji>'

def safe(t):
    return html.escape(str(t))

# ─── BUTTON / KEYBOARD HELPERS ──────────────────────────────────────────────
def btn(text, cb, style=None, icon=None):
    b = {"text": text, "callback_data": cb}
    if style: b["style"] = style
    if icon:  b["icon_custom_emoji_id"] = icon
    return b

def kb(*rows):
    return {"inline_keyboard": [r if isinstance(r, list) else [r] for r in rows]}

# ─── DATABASE ────────────────────────────────────────────────────────────────
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def get_user(db, uid, name="Игрок"):
    if uid not in db:
        db[uid] = {
            "name": name, "balance": 2_500_000,
            "joined": str(date.today()), "last_bonus": None,
            "referrals": [], "referred_by": None, "verified": False,
            "banned": False,
            "stats": {"wins": 0, "losses": 0, "draws": 0},
            "transfer_count": {"date": "", "count": 0},
            "activated_promos": [], "created_promo": None,
            "user_logs": [],
        }
    else:
        db[uid]["name"] = name
    return db[uid]

def fmt(n):
    return "${:,.0f}".format(n).replace(",", ".")

def add_log(db, uid, action, detail=""):
    if uid not in db: return
    logs = db[uid].get("user_logs", [])
    logs.insert(0, {"time": datetime.now().strftime("%d.%m.%Y %H:%M"),
                     "action": action, "detail": detail})
    db[uid]["user_logs"] = logs[:30]

# ─── PROMOS DB ──────────────────────────────────────────────────────────────
def load_promos():
    if os.path.exists(PROMO_FILE):
        with open(PROMO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"admin": {}, "user": {}}

def save_promos(p):
    with open(PROMO_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)

# ─── TRANSFER LIMIT ─────────────────────────────────────────────────────────
def can_transfer(user):
    tc = user.get("transfer_count", {"date": "", "count": 0})
    if tc["date"] != str(date.today()): return True
    return tc["count"] < 2

def did_transfer(user):
    today = str(date.today())
    tc = user.get("transfer_count", {"date": "", "count": 0})
    if tc["date"] != today:
        user["transfer_count"] = {"date": today, "count": 1}
    else:
        user["transfer_count"] = {"date": today, "count": tc["count"] + 1}

# ─── FSM STATES ─────────────────────────────────────────────────────────────
class PayStates(StatesGroup):
    waiting_id = State()
    waiting_amount = State()

class PromoStates(StatesGroup):
    enter_admin_code = State()
    enter_user_code = State()
    create_code = State()

class AdminStates(StatesGroup):
    broadcast = State()
    target_id = State()
    amount = State()
    promo_code = State()
    promo_amount = State()

# ─── SESSIONS ───────────────────────────────────────────────────────────────
sessions = {}
captcha_data = {}

# ─── KEYBOARDS ──────────────────────────────────────────────────────────────
def main_menu_kb(is_admin=False):
    rows = [
        [btn("🎮  Игры", "cat_games", style="success", icon=EI_OK)],
        [btn("🎁  Бонусы и рефералы", "cat_bonus", style="success", icon=EI_OK)],
        [btn("📊  Информация", "cat_info", style="primary", icon=EI_LIKE)],
        [btn("🏆  Рейтинг", "cat_rating", style="primary", icon=EI_LIKE)],
        [btn("🎟️  Промокоды", "cat_promo", style="primary", icon=EI_STAR)],
    ]
    if is_admin:
        rows.append([btn("🛠️  Админ-панель", "admin_panel", style="danger", icon=EI_WARN)])
    return {"inline_keyboard": rows}

def games_kb():
    return kb(
        [btn("⚽  Футбол — x2", "game_football", style="success", icon=EI_OK)],
        [btn("💣  Мины — x2", "game_mines", style="danger", icon=EI_WARN)],
        [btn("🏀  Баскетбол — x2", "game_basketball", style="success", icon=EI_OK)],
        [btn("❌⭕  Крестики-нолики", "game_ttt", style="primary", icon=EI_LIKE)],
        [btn("🔙  В меню", "main_menu", icon=EI_STAR)])

def bonus_kb():
    return kb(
        [btn("🎁  Ежедневный бонус", "daily_bonus", style="success", icon=EI_OK)],
        [btn("👥  Реферальная прогр.", "referral", style="primary", icon=EI_LIKE)],
        [btn("🔙  В меню", "main_menu", icon=EI_STAR)])

def info_kb():
    return kb(
        [btn("💰  Баланс", "balance", style="success", icon=EI_OK)],
        [btn("📊  Статистика", "stats", style="primary", icon=EI_LIKE)],
        [btn("🔙  В меню", "main_menu", icon=EI_STAR)])

def rating_kb():
    return kb(
        [btn("💰  По балансу", "rating_balance", style="success", icon=EI_OK)],
        [btn("🏆  По победам", "rating_wins", style="primary", icon=EI_LIKE)],
        [btn("💀  По поражениям", "rating_losses", style="danger", icon=EI_WARN)],
        [btn("🔙  В меню", "main_menu", icon=EI_STAR)])

def promo_kb():
    return kb(
        [btn("🎟️  Ввести промокод", "promo_enter", style="success", icon=EI_OK)],
        [btn("👤  Промокод пользователя", "promo_user_enter", style="primary", icon=EI_LIKE)],
        [btn("➕  Создать свой промокод", "promo_create", style="success", icon=EI_OK)],
        [btn("📋  Мой промокод", "promo_my", style="primary", icon=EI_STAR)],
        [btn("🔙  В меню", "main_menu", icon=EI_STAR)])

def admin_kb():
    return kb(
        [btn("📢  Рассылка", "admin_broadcast", style="danger", icon=EI_WARN),
         btn("🔨  Бан/Разбан", "admin_ban_unban", style="danger", icon=EI_WARN)],
        [btn("💰  Баланс игрока", "admin_check_balance", style="primary", icon=EI_LIKE),
         btn("📋  Логи игрока", "admin_logs", style="primary", icon=EI_LIKE)],
        [btn("💸  Выдать $", "admin_give", style="success", icon=EI_OK),
         btn("📥  Забрать $", "admin_take", style="danger", icon=EI_WARN)],
        [btn("🎟️  Создать промокод", "admin_create_promo", style="success", icon=EI_OK)],
        [btn("🔙  В меню", "main_menu", icon=EI_STAR)])

def back_kb():
    return kb([btn("🔙  В меню", "main_menu", icon=EI_STAR)])

def back_promo_kb():
    return kb([btn("🔙  Промокоды", "cat_promo", style="primary", icon=EI_STAR),
               btn("🏠  Меню", "main_menu", icon=EI_STAR)])

def back_admin_kb():
    return kb([btn("🔙  Админ", "admin_panel", style="danger", icon=EI_WARN),
               btn("🏠  Меню", "main_menu", icon=EI_STAR)])

def game_nav_kb(game_cb):
    return kb(
        [btn("🔄  Ещё раз", game_cb, style="success", icon=EI_OK),
         btn("🎮  Игры", "cat_games", style="primary", icon=EI_LIKE)],
        [btn("🏠  Меню", "main_menu", icon=EI_STAR)])

def cancel_kb():
    return kb([btn("❌  Отмена", "cancel_fsm", style="danger", icon=EI_WARN)])

def bet_kb(game):
    bets = [100_000, 500_000, 1_000_000, 5_000_000, 10_000_000]
    rows = []
    for i in range(0, len(bets), 2):
        row = [btn(f"💵 {fmt(bets[j])}", f"bet_{game}_{bets[j]}", style="success", icon=EI_OK)
               for j in range(i, min(i+2, len(bets)))]
        rows.append(row)
    rows.append([btn("🔙  В меню", "main_menu", icon=EI_STAR)])
    return {"inline_keyboard": rows}

# ─── TEXT HELPERS ────────────────────────────────────────────────────────────
def main_menu_text(name, user):
    s = user["stats"]
    bonus = "✅ Получен" if user["last_bonus"] == str(date.today()) else f"{ae('🎁', EI_OK)} Доступен"
    return (
        f"<b>gamGems</b>\n\n"
        f"👤 <b>{safe(name)}</b>\n"
        f"💰 Баланс: <code>{fmt(user['balance'])}</code>\n"
        f"{bonus}\n\n"
        f"🏆 Побед: <b>{s['wins']}</b>  |  "
        f"💀 Поражений: <b>{s['losses']}</b>\n\n"
        f"🎮 <i>Выбери категорию:</i>")

# ─── CAPTCHA ─────────────────────────────────────────────────────────────────
def make_captcha():
    a, b = random.randint(2, 15), random.randint(2, 15)
    op = random.choice(["+", "-", "×"])
    ans = a + b if op == "+" else (a - b if op == "-" else a * b)
    wrong = set()
    while len(wrong) < 3:
        w = ans + random.randint(-8, 8)
        if w != ans: wrong.add(w)
    opts = list(wrong) + [ans]; random.shuffle(opts)
    return f"{a} {op} {b} = ?", ans, opts

def captcha_kb(opts):
    rows = []
    for i in range(0, len(opts), 2):
        row = [btn(str(opts[j]), f"captcha_{opts[j]}", style="primary", icon=EI_STAR)
               for j in range(i, min(i+2, len(opts)))]
        rows.append(row)
    return {"inline_keyboard": rows}

# ─── GENERIC CANCEL ─────────────────────────────────────────────────────────
@dp.callback_query(F.data == "cancel_fsm")
async def cancel_fsm_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    db = load_db()
    uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name)
    save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        "❌ Отменено.", main_menu_kb(is_admin=(uid == ADMIN_ID)))
    await cb.answer("❌ Отменено")

# ─── /start ─────────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(msg: Message):
    db = load_db()
    uid = str(msg.from_user.id)
    name = msg.from_user.first_name or "Игрок"
    user = get_user(db, uid, name)

    pending_ref = None
    args = msg.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        pending_ref = args[1][4:]

    if msg.chat.type in ("group", "supergroup"):
        user["verified"] = True

    if not user["verified"]:
        q, ans, opts = make_captcha()
        captcha_data[uid] = {"ans": ans, "pending_ref": pending_ref}
        save_db(db)
        await send_msg(msg.chat.id,
            f"🤖 <b>Докажи, что ты не бот!</b>\n\nРеши пример: <b>{q}</b>",
            captcha_kb(opts))
        return

    if user.get("banned"):
        await send_msg(msg.chat.id, "🚫 Ты заблокирован!")
        save_db(db); return

    save_db(db)
    await send_msg(msg.chat.id, main_menu_text(name, user),
        main_menu_kb(is_admin=(uid == ADMIN_ID)))

# ─── /help ──────────────────────────────────────────────────────────────────
@dp.message(Command("help"))
async def cmd_help(msg: Message):
    await send_msg(msg.chat.id,
        "<b>📖 Команды gamGems:</b>\n\n"
        "🎮 <b>Игры</b> — только в группах:\n"
        "   ⚽ Футбол, 💣 Мины, 🏀 Баскетбол, ❌⭕ Крестики\n\n"
        "💰 <b>/б</b> — проверить баланс\n"
        "💸 <b>/pay</b> — перевод игроку (комиссия 20%, 2/день)\n"
        "   <i>/pay 1000000 123456789</i>\n"
        "   <i>Reply + /pay 1000000</i>\n"
        "🎁 <b>Бонус</b> — $1.000.000 каждый день\n"
        "👥 <b>Рефералы</b> — $5.000.000 за друга\n"
        "🎟️ <b>Промокоды</b> — вводи и создавай\n"
        "🏆 <b>Рейтинг</b> — топ игроков")

# ─── /б ─────────────────────────────────────────────────────────────────────
@dp.message(Command("б", "b"))
async def cmd_balance_short(msg: Message):
    db = load_db(); uid = str(msg.from_user.id)
    user = get_user(db, uid, msg.from_user.first_name); save_db(db)
    await send_msg(msg.chat.id,
        f"💰 <b>Твой баланс:</b> <code>{fmt(user['balance'])}</code>")

# ─── /pay ───────────────────────────────────────────────────────────────────
async def do_pay(src, db, uid, target_id, amount):
    """Возвращает (ok, text)"""
    user = db[uid]
    if not can_transfer(user):
        return False, "❌ Лимит: 2 перевода в день!"
    if target_id == uid:
        return False, "❌ Нельзя перевести самому себе!"
    if target_id not in db or not db[target_id].get("verified"):
        return False, "❌ Игрок не найден!"
    if db[target_id].get("banned"):
        return False, "❌ Игрок заблокирован!"
    if user["balance"] < amount:
        return False, f"❌ Недостаточно средств!\nБаланс: <code>{fmt(user['balance'])}</code>"
    received = int(amount * 0.8); commission = amount - received
    user["balance"] -= amount; db[target_id]["balance"] += received
    did_transfer(user)
    tname = db[target_id].get("name", "Игрок")
    add_log(db, uid, "transfer", f"-{fmt(amount)} → {safe(tname)}")
    add_log(db, target_id, "transfer_in", f"+{fmt(received)} ← {safe(src.from_user.first_name)}")
    try:
        await send_msg(int(target_id),
            f"💸 <b>Входящий перевод!</b>\n\n"
            f"👤 От: <b>{safe(src.from_user.first_name)}</b>\n"
            f"💰 Получено: <code>{fmt(received)}</code>\n\n"
            f"Баланс: <code>{fmt(db[target_id]['balance'])}</code>")
    except Exception: pass
    return True, (
        f"✅ <b>Перевод выполнен!</b>\n\n"
        f"👤 <b>{safe(tname)}</b>\n"
        f"💰 Отправлено: <code>{fmt(amount)}</code>\n"
        f"📊 Комиссия: <code>{fmt(commission)}</code>\n"
        f"📬 Доставлено: <code>{fmt(received)}</code>\n\n"
        f"Баланс: <code>{fmt(user['balance'])}</code>")

def parse_amount(s):
    s = s.replace("$","").replace(".","").replace(",","")
    return int(s) if s.isdigit() and int(s) > 0 else None

@dp.message(Command("pay"))
async def cmd_pay(msg: Message, state: FSMContext):
    db = load_db(); uid = str(msg.from_user.id)
    user = get_user(db, uid, msg.from_user.first_name)
    if not user.get("verified"):
        await send_msg(msg.chat.id, "❌ Сначала /start"); return
    if user.get("banned"):
        await send_msg(msg.chat.id, "🚫 Заблокирован!"); return
    save_db(db)

    parts = msg.text.split()
    # /pay <amount> <id>
    if len(parts) >= 3:
        amount = parse_amount(parts[1])
        tid = parts[2]
        if not amount:
            await send_msg(msg.chat.id, "❌ Неверная сумма!"); return
        if not tid.isdigit():
            await send_msg(msg.chat.id, "❌ ID — число!"); return
        db = load_db()
        ok, text = await do_pay(msg, db, uid, tid, amount)
        if ok: save_db(db)
        await send_msg(msg.chat.id, text); return

    # /pay <amount> (reply)
    if len(parts) == 2 and msg.reply_to_message:
        amount = parse_amount(parts[1])
        if not amount:
            await send_msg(msg.chat.id, "❌ Неверная сумма!"); return
        tid = str(msg.reply_to_message.from_user.id)
        db = load_db()
        ok, text = await do_pay(msg, db, uid, tid, amount)
        if ok: save_db(db)
        await send_msg(msg.chat.id, text); return

    # Interactive
    await state.set_state(PayStates.waiting_id)
    await send_msg(msg.chat.id,
        f"💸 <b>Перевод</b>\n\n"
        f"💰 Баланс: <code>{fmt(user['balance'])}</code>\n"
        f"📊 Комиссия: 20% | Лимит: 2/день\n\n"
        f"👤 Введи <b>ID получателя</b>:",
        cancel_kb())

@dp.message(PayStates.waiting_id)
async def pay_id(msg: Message, state: FSMContext):
    txt = msg.text.strip()
    if not txt.isdigit():
        await send_msg(msg.chat.id, "❌ ID — число!", cancel_kb()); return
    uid = str(msg.from_user.id)
    if txt == uid:
        await send_msg(msg.chat.id, "❌ Нельзя себе!", cancel_kb()); return
    db = load_db()
    if txt not in db or not db[txt].get("verified"):
        await send_msg(msg.chat.id, "❌ Не найден!", cancel_kb()); return
    await state.update_data(rid=txt)
    await state.set_state(PayStates.waiting_amount)
    await send_msg(msg.chat.id,
        f"✅ Игрок: <b>{safe(db[txt]['name'])}</b>\n\n"
        f"💰 Введи <b>сумму</b>:", cancel_kb())

@dp.message(PayStates.waiting_amount)
async def pay_amount(msg: Message, state: FSMContext):
    amount = parse_amount(msg.text.strip())
    if not amount:
        await send_msg(msg.chat.id, "❌ Неверная сумма!", cancel_kb()); return
    data = await state.get_data(); rid = data["rid"]
    db = load_db(); uid = str(msg.from_user.id)
    ok, text = await do_pay(msg, db, uid, rid, amount)
    await state.clear()
    if ok: save_db(db)
    await send_msg(msg.chat.id, text, back_kb() if ok else None)

# ─── CAPTCHA CALLBACK ───────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("captcha_"))
async def captcha_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id)
    chosen = int(cb.data.split("_")[1])
    data = captcha_data.get(uid, {})
    if chosen != data.get("ans"):
        q, ans, opts = make_captcha()
        captcha_data[uid] = {"ans": ans, "pending_ref": data.get("pending_ref")}
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"❌ <b>Неверно!</b>\n\nРеши: <b>{q}</b>", captcha_kb(opts))
        await cb.answer("Неверно!"); return

    db = load_db()
    user = get_user(db, uid, cb.from_user.first_name)
    user["verified"] = True
    ref_id = data.get("pending_ref")
    if ref_id and ref_id != uid and ref_id in db:
        if uid not in db[ref_id]["referrals"]:
            db[ref_id]["referrals"].append(uid)
            db[ref_id]["balance"] += 5_000_000
            user["referred_by"] = ref_id
            try:
                await send_msg(int(ref_id),
                    f"🎉 Новый игрок по ссылке!\n💰 <b>+{fmt(5_000_000)}</b>")
            except Exception: pass
    save_db(db); captcha_data.pop(uid, None)
    await cb.answer("✅ Пройдена!")
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        main_menu_text(cb.from_user.first_name, user),
        main_menu_kb(is_admin=(uid == ADMIN_ID)))

# ─── MAIN MENU ──────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "main_menu")
async def main_menu_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name); save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        main_menu_text(cb.from_user.first_name, user),
        main_menu_kb(is_admin=(uid == ADMIN_ID)))
    await cb.answer()

# ─── CATEGORY CALLBACKS ─────────────────────────────────────────────────────
@dp.callback_query(F.data == "cat_games")
async def cat_games_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name); save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🎮 <b>ИГРЫ</b>\n\n"
        f"💰 Баланс: <code>{fmt(user['balance'])}</code>\n\n"
        f"⚽ Футбол — угадай направление\n"
        f"💣 Мины — открой клетки без мин\n"
        f"🏀 Баскетбол — забрось в кольцо\n"
        f"❌⭕ Крестики — победи бота\n\n"
        f"<i>Все x2! Только в группах.</i>", games_kb())
    await cb.answer()

@dp.callback_query(F.data == "cat_bonus")
async def cat_bonus_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name); save_db(db)
    bs = "✅ Получен" if user["last_bonus"] == str(date.today()) else f"{ae('🎁', EI_OK)} Доступен"
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🎁 <b>БОНУСЫ</b>\n\n"
        f"💰 Баланс: <code>{fmt(user['balance'])}</code>\n\n"
        f"🎁 Бонус: <b>$1.000.000</b>/день — {bs}\n"
        f"👥 Друзей: <b>{len(user['referrals'])}</b> — <b>$5.000.000</b>/друг",
        bonus_kb())
    await cb.answer()

@dp.callback_query(F.data == "cat_info")
async def cat_info_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name); save_db(db)
    s = user["stats"]; total = sum(s.values())
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"📊 <b>ИНФОРМАЦИЯ</b>\n\n"
        f"👤 <b>{safe(cb.from_user.first_name)}</b>\n"
        f"📅 С: <b>{user['joined']}</b>\n\n"
        f"💰 <code>{fmt(user['balance'])}</code>\n"
        f"🎮 Игр: <b>{total}</b> | 🏆 <b>{s['wins']}</b> | 💀 <b>{s['losses']}</b>",
        info_kb())
    await cb.answer()

@dp.callback_query(F.data == "cat_rating")
async def cat_rating_cb(cb: CallbackQuery):
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🏆 <b>РЕЙТИНГ</b>\n\n"
        f"💰 По балансу\n🏆 По победам\n💀 По поражениям",
        rating_kb())
    await cb.answer()

@dp.callback_query(F.data == "cat_promo")
async def cat_promo_cb(cb: CallbackQuery):
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🎟️ <b>ПРОМОКОДЫ</b>\n\n"
        f"🎟️ <b>Ввести</b> — админский промокод\n"
        f"👤 <b>Пользовательский</b> — от игроков\n"
        f"➕ <b>Создать</b> — свой промокод (+$500.000/активация)\n"
        f"📋 <b>Мой</b> — статистика",
        promo_kb())
    await cb.answer()

# ─── RATING ─────────────────────────────────────────────────────────────────
def build_lb(db, uid, key, title, emoji):
    users = []
    for u_id, u in db.items():
        if not u.get("verified"): continue
        name = u.get("name", "").strip()
        if not name: continue
        if key == "balance": val, vf = u["balance"], fmt(u["balance"])
        elif key == "wins": val, vf = u["stats"]["wins"], str(u["stats"]["wins"])
        else: val, vf = u["stats"]["losses"], str(u["stats"]["losses"])
        users.append((u_id, name, val, vf))
    users.sort(key=lambda x: x[2], reverse=True)
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    lines = [f"{emoji} <b>{title}</b>\n"]
    for i, (u_id, name, val, vf) in enumerate(users[:10]):
        m = medals.get(i, f" {i+1}.")
        me = " ◀️ <i>ты</i>" if u_id == uid else ""
        lines.append(f"{m} <b>{safe(name)}</b> — {vf}{me}")
    pos = next((i+1 for i, (u_id, *_) in enumerate(users) if u_id == uid), None)
    if pos: lines.append(f"\n📍 Ты: <b>{pos}</b> из <b>{len(users)}</b>")
    return "\n".join(lines)

def rating_back_kb():
    return kb([btn("🔙  Рейтинг", "cat_rating", style="primary", icon=EI_STAR),
               btn("🏠  Меню", "main_menu", icon=EI_STAR)])

@dp.callback_query(F.data == "rating_balance")
async def rating_bal_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id); get_user(db, uid, cb.from_user.first_name); save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        build_lb(db, uid, "balance", "По балансу", "💰"), rating_back_kb())
    await cb.answer()

@dp.callback_query(F.data == "rating_wins")
async def rating_wins_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id); get_user(db, uid, cb.from_user.first_name); save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        build_lb(db, uid, "wins", "По победам", "🏆"), rating_back_kb())
    await cb.answer()

@dp.callback_query(F.data == "rating_losses")
async def rating_losses_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id); get_user(db, uid, cb.from_user.first_name); save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        build_lb(db, uid, "losses", "По поражениям", "💀"), rating_back_kb())
    await cb.answer()

# ─── BALANCE / STATS / BONUS / REFERRAL ─────────────────────────────────────
@dp.callback_query(F.data == "balance")
async def balance_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name); save_db(db); s = user["stats"]
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"💰 <b>БАЛАНС</b>\n\n{ae('💵', EI_OK)} <code>{fmt(user['balance'])}</code>\n\n"
        f"🏆 <b>{s['wins']}</b> | 💀 <b>{s['losses']}</b> | 🤝 <b>{s['draws']}</b>", back_kb())
    await cb.answer()

@dp.callback_query(F.data == "stats")
async def stats_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name); save_db(db)
    s = user["stats"]; total = sum(s.values())
    if total == 0: rank = "🥉 Новичок"
    elif s["wins"]/total >= 0.7: rank = f"{ae('👑', EI_OK)} Легенда"
    elif s["wins"]/total >= 0.55: rank = f"{ae('💎', EI_LIKE)} Мастер"
    elif s["wins"]/total >= 0.45: rank = f"{ae('⭐', EI_STAR)} Опытный"
    else: rank = "🥉 Новичок"
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"📊 <b>СТАТИСТИКА</b>\n\n{rank}\n\n"
        f"🎮 Игр: <b>{total}</b>\n🏆 Побед: <b>{s['wins']}</b>\n"
        f"💀 Поражений: <b>{s['losses']}</b>\n🤝 Ничьих: <b>{s['draws']}</b>\n\n"
        f"💰 <code>{fmt(user['balance'])}</code>", back_kb())
    await cb.answer()

@dp.callback_query(F.data == "daily_bonus")
async def daily_bonus_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name)
    today = str(date.today())
    if user["last_bonus"] == today:
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"🎁 <b>Бонус</b>\n\n⏰ Уже получен сегодня!\nЗавтра — <b>$1.000.000</b>\n\n"
            f"Баланс: <code>{fmt(user['balance'])}</code>", back_kb())
    else:
        user["balance"] += 1_000_000; user["last_bonus"] = today
        add_log(db, uid, "bonus", "+$1.000.000"); save_db(db)
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"🎁 <b>Бонус!</b>\n\n{ae('🎉', EI_OK)} <b>+$1.000.000</b>\n\n"
            f"Баланс: <code>{fmt(user['balance'])}</code>", back_kb())
    await cb.answer()

@dp.callback_query(F.data == "referral")
async def referral_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name); save_db(db)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{uid}"
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"👥 <b>Рефералы</b>\n\n"
        f"💰 <b>+$5.000.000</b> за друга\n"
        f"👥 Приглашено: <b>{len(user['referrals'])}</b>\n\n"
        f"🔗 <code>{link}</code>", back_kb())
    await cb.answer()

# ═══════════════════════════════════════════════════════════════════════════════
# ПРОМОКОДЫ
# ═══════════════════════════════════════════════════════════════════════════════
@dp.callback_query(F.data == "promo_enter")
async def promo_enter_cb(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PromoStates.enter_admin_code)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🎟️ <b>Ввести промокод</b>\n\nВведи код:", cancel_kb())
    await cb.answer()

@dp.message(PromoStates.enter_admin_code)
async def promo_admin_code(msg: Message, state: FSMContext):
    code = msg.text.strip().upper()
    db = load_db(); promos = load_promos()
    uid = str(msg.from_user.id); user = get_user(db, uid, msg.from_user.first_name)
    if code not in promos.get("admin", {}):
        await send_msg(msg.chat.id, "❌ Не найден! Ещё раз:", cancel_kb()); return
    activated = db[uid].get("activated_promos", [])
    if code in activated:
        await state.clear()
        await send_msg(msg.chat.id, "❌ Уже активирован!", back_promo_kb()); return
    amount = promos["admin"][code]["amount"]
    user["balance"] += amount
    db[uid].setdefault("activated_promos", []).append(code)
    add_log(db, uid, "promo", f"+{fmt(amount)} ({code})")
    save_db(db); save_promos(promos); await state.clear()
    await send_msg(msg.chat.id,
        f"✅ <b>Активирован!</b>\n\n🎟️ <code>{code}</code>\n"
        f"💰 +<code>{fmt(amount)}</code>\n\nБаланс: <code>{fmt(user['balance'])}</code>",
        back_promo_kb())

@dp.callback_query(F.data == "promo_user_enter")
async def promo_user_enter_cb(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PromoStates.enter_user_code)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"👤 <b>Промокод пользователя</b>\n\n"
        f"Введи код от другого игрока:\n"
        f"<i>Активатор: +$100.000 | Автор: +$500.000</i>", cancel_kb())
    await cb.answer()

@dp.message(PromoStates.enter_user_code)
async def promo_user_code(msg: Message, state: FSMContext):
    code = msg.text.strip().upper()
    db = load_db(); promos = load_promos()
    uid = str(msg.from_user.id); user = get_user(db, uid, msg.from_user.first_name)
    if code not in promos.get("user", {}):
        await send_msg(msg.chat.id, "❌ Не найден! Ещё раз:", cancel_kb()); return
    promo = promos["user"][code]; creator_id = promo["creator_id"]
    if creator_id == uid:
        await send_msg(msg.chat.id, "❌ Это твой промокод!", cancel_kb()); return
    if uid in promo.get("activated_by", []):
        await send_msg(msg.chat.id, "❌ Уже активирован!", cancel_kb()); return
    # Награды
    user["balance"] += 100_000
    if creator_id in db:
        db[creator_id]["balance"] += 500_000
        try:
            await send_msg(int(creator_id),
                f"🎟️ Твой промо активирован!\n💰 +<code>{fmt(500_000)}</code>")
        except Exception: pass
    promo.setdefault("activated_by", []).append(uid)
    promo["activations"] = len(promo["activated_by"])
    add_log(db, uid, "user_promo", f"+{fmt(100_000)} ({code})")
    save_db(db); save_promos(promos); await state.clear()
    await send_msg(msg.chat.id,
        f"✅ <b>Активирован!</b>\n\n🎟️ <code>{code}</code>\n"
        f"💰 +<code>{fmt(100_000)}</code>\n\nБаланс: <code>{fmt(user['balance'])}</code>",
        back_promo_kb())

@dp.callback_query(F.data == "promo_create")
async def promo_create_cb(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PromoStates.create_code)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"➕ <b>Создать промокод</b>\n\n"
        f"Код (3-15, латиница+цифры):\n"
        f"<i>+ $500.000 за каждую активацию</i>", cancel_kb())
    await cb.answer()

@dp.message(PromoStates.create_code)
async def promo_create_msg(msg: Message, state: FSMContext):
    code = msg.text.strip().upper()
    uid = str(msg.from_user.id)
    if len(code) < 3 or len(code) > 15 or not code.isalnum():
        await send_msg(msg.chat.id, "❌ 3-15 символов, латиница+цифры!", cancel_kb()); return
    promos = load_promos()
    if code in promos.get("admin", {}) or code in promos.get("user", {}):
        await send_msg(msg.chat.id, "❌ Занят! Другой:", cancel_kb()); return
    promos.setdefault("user", {})[code] = {"creator_id": uid, "activations": 0, "activated_by": []}
    db = load_db(); get_user(db, uid, msg.from_user.first_name)
    db[uid]["created_promo"] = code
    save_db(db); save_promos(promos); await state.clear()
    await send_msg(msg.chat.id,
        f"✅ <b>Создан!</b>\n\n🎟️ <code>{code}</code>\n"
        f"💰 +$500.000 за каждую активацию\n\n"
        f"<i>Поделись с друзьями!</i>", back_promo_kb())

@dp.callback_query(F.data == "promo_my")
async def promo_my_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name); save_db(db)
    code = user.get("created_promo")
    if not code:
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"📋 <b>Мой промокод</b>\n\nПока нет. Создай в разделе выше!",
            back_promo_kb()); await cb.answer(); return
    promos = load_promos()
    p = promos.get("user", {}).get(code, {})
    acts = p.get("activations", 0)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"📋 <b>Мой промокод</b>\n\n🎟️ <code>{code}</code>\n"
        f"👥 Активаций: <b>{acts}</b>\n"
        f"💰 Заработано: <code>{fmt(acts * 500_000)}</code>",
        back_promo_kb())
    await cb.answer()

# ═══════════════════════════════════════════════════════════════════════════════
# АДМИН-ПАНЕЛЬ (только ID 8144110555)
# ═══════════════════════════════════════════════════════════════════════════════
def admin_only(cb):
    return str(cb.from_user.id) == ADMIN_ID

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_cb(cb: CallbackQuery):
    if not admin_only(cb): await cb.answer("❌", show_alert=True); return
    db = load_db()
    total = sum(1 for u in db.values() if u.get("verified"))
    bal = sum(u.get("balance", 0) for u in db.values())
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🛠️ <b>АДМИН</b>\n\n👥 Игроков: <b>{total}</b>\n"
        f"💰 Сумма: <code>{fmt(bal)}</code>", admin_kb())
    await cb.answer()

# Рассылка
@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.broadcast)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"📢 <b>Рассылка</b>\n\nВведи текст:", cancel_kb())
    await cb.answer()

@dp.message(AdminStates.broadcast)
async def admin_broadcast_msg(msg: Message, state: FSMContext):
    if str(msg.from_user.id) != ADMIN_ID: await state.clear(); return
    db = load_db(); sent = fail = 0
    for u_id, u in db.items():
        if not u.get("verified"): continue
        try: await send_msg(int(u_id), msg.text); sent += 1
        except: fail += 1
    await state.clear()
    await send_msg(msg.chat.id,
        f"✅ <b>Рассылка</b>\n\n📬 {sent} | ❌ {fail}", admin_kb())

# Бан/Разбан
@dp.callback_query(F.data == "admin_ban_unban")
async def admin_ban_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.target_id)
    await state.update_data(action="ban")
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🔨 <b>Бан/Разбан</b>\n\nID игрока:", cancel_kb())
    await cb.answer()

# Баланс игрока
@dp.callback_query(F.data == "admin_check_balance")
async def admin_checkbal_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.target_id)
    await state.update_data(action="balance")
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"💰 <b>Баланс игрока</b>\n\nID:", cancel_kb())
    await cb.answer()

# Логи
@dp.callback_query(F.data == "admin_logs")
async def admin_logs_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.target_id)
    await state.update_data(action="logs")
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"📋 <b>Логи</b>\n\nID:", cancel_kb())
    await cb.answer()

# Выдать
@dp.callback_query(F.data == "admin_give")
async def admin_give_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.target_id)
    await state.update_data(action="give")
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"💸 <b>Выдать $</b>\n\nID:", cancel_kb())
    await cb.answer()

# Забрать
@dp.callback_query(F.data == "admin_take")
async def admin_take_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.target_id)
    await state.update_data(action="take")
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"📥 <b>Забрать $</b>\n\nID:", cancel_kb())
    await cb.answer()

# Создать промокод (админ)
@dp.callback_query(F.data == "admin_create_promo")
async def admin_promo_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.promo_code)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🎟️ <b>Создать промокод</b>\n\nКод (3-15, латиница+цифры):", cancel_kb())
    await cb.answer()

# Shared: target_id
@dp.message(AdminStates.target_id)
async def admin_target_id(msg: Message, state: FSMContext):
    if str(msg.from_user.id) != ADMIN_ID: await state.clear(); return
    tid = msg.text.strip()
    if not tid.isdigit():
        await send_msg(msg.chat.id, "❌ ID — число!", cancel_kb()); return
    data = await state.get_data(); action = data["action"]
    db = load_db()
    if tid not in db:
        await send_msg(msg.chat.id, "❌ Не найден!", cancel_kb()); return
    tname = db[tid].get("name", "—")

    if action == "ban":
        banned = db[tid].get("banned", False)
        db[tid]["banned"] = not banned
        add_log(db, tid, "ban" if not banned else "unban", "admin")
        save_db(db); await state.clear()
        st = "🔒 ЗАБАНЕН" if not banned else "✅ РАЗБАНЕН"
        await send_msg(msg.chat.id,
            f"✅ <b>{st}</b>\n\n👤 <b>{safe(tname)}</b> (<code>{tid}</code>)", admin_kb())

    elif action == "balance":
        s = db[tid].get("stats", {"wins":0,"losses":0,"draws":0})
        await state.clear()
        await send_msg(msg.chat.id,
            f"💰 <b>Баланс</b>\n\n👤 <b>{safe(tname)}</b> (<code>{tid}</code>)\n"
            f"💰 <code>{fmt(db[tid]['balance'])}</code>\n"
            f"🏆 {s['wins']} | 💀 {s['losses']} | 🤝 {s['draws']}", admin_kb())

    elif action == "logs":
        logs = db[tid].get("user_logs", [])
        lines = [f"📋 <b>{safe(tname)}</b> (<code>{tid}</code>)\n"]
        if not logs: lines.append("Пусто.")
        else:
            for l in logs[:20]:
                lines.append(f"[{l.get('time','')}] {l.get('action','')} — {l.get('detail','')}")
        await state.clear()
        await send_msg(msg.chat.id, "\n".join(lines), admin_kb())

    elif action in ("give", "take"):
        await state.update_data(target_id=tid)
        await state.set_state(AdminStates.amount)
        w = "Выдать" if action == "give" else "Забрать"
        await send_msg(msg.chat.id,
            f"{'💸' if action=='give' else '📥'} <b>{w}</b>\n\n"
            f"👤 <b>{safe(tname)}</b> — <code>{fmt(db[tid]['balance'])}</code>\n\nСумма:",
            cancel_kb())

# Shared: amount
@dp.message(AdminStates.amount)
async def admin_amount_msg(msg: Message, state: FSMContext):
    if str(msg.from_user.id) != ADMIN_ID: await state.clear(); return
    amount = parse_amount(msg.text.strip())
    if not amount:
        await send_msg(msg.chat.id, "❌ Неверная сумма!", cancel_kb()); return
    data = await state.get_data(); action = data["action"]; tid = data["target_id"]
    db = load_db(); tname = db[tid].get("name", "—")
    if action == "give":
        db[tid]["balance"] += amount
        add_log(db, tid, "admin_give", f"+{fmt(amount)}"); w = "Выдано"
    else:
        db[tid]["balance"] = max(0, db[tid].get("balance", 0) - amount)
        add_log(db, tid, "admin_take", f"-{fmt(amount)}"); w = "Списано"
    save_db(db); await state.clear()
    await send_msg(msg.chat.id,
        f"✅ <b>{w}: {fmt(amount)}</b>\n\n👤 <b>{safe(tname)}</b>\n"
        f"💰 <code>{fmt(db[tid]['balance'])}</code>", admin_kb())

# Admin promo: code
@dp.message(AdminStates.promo_code)
async def admin_promo_code_msg(msg: Message, state: FSMContext):
    if str(msg.from_user.id) != ADMIN_ID: await state.clear(); return
    code = msg.text.strip().upper()
    if len(code) < 3 or len(code) > 15 or not code.isalnum():
        await send_msg(msg.chat.id, "❌ 3-15, латиница+цифры!", cancel_kb()); return
    promos = load_promos()
    if code in promos.get("admin", {}) or code in promos.get("user", {}):
        await send_msg(msg.chat.id, "❌ Занят!", cancel_kb()); return
    await state.update_data(promo_code=code)
    await state.set_state(AdminStates.promo_amount)
    await send_msg(msg.chat.id, f"🎟️ Код: <code>{code}</code>\n\nСумма награды:", cancel_kb())

@dp.message(AdminStates.promo_amount)
async def admin_promo_amount_msg(msg: Message, state: FSMContext):
    if str(msg.from_user.id) != ADMIN_ID: await state.clear(); return
    amount = parse_amount(msg.text.strip())
    if not amount:
        await send_msg(msg.chat.id, "❌ Неверная сумма!", cancel_kb()); return
    data = await state.get_data(); code = data["promo_code"]
    promos = load_promos()
    promos.setdefault("admin", {})[code] = {"amount": amount, "created": str(date.today())}
    save_promos(promos); await state.clear()
    await send_msg(msg.chat.id,
        f"✅ <b>Создан!</b>\n\n🎟️ <code>{code}</code>\n💰 <code>{fmt(amount)}</code>",
        admin_kb())

# ═══════════════════════════════════════════════════════════════════════════════
# ИГРЫ — СТАВКИ
# ═══════════════════════════════════════════════════════════════════════════════
GAME_INFO = {
    "football":   ("⚽ Футбол",    "Угадай направление удара!\nВыиграй x2! 🥅"),
    "mines":      ("💣 Мины",      "Открой все клетки без мин!\nПриз x2! 💎"),
    "basketball": ("🏀 Баскетбол", "Забрось мяч в кольцо!\nУгадай — x2! 🏀"),
    "ttt":        ("❌⭕ Крестики","Победи бота!\nПриз x2! 🎯"),
}

def is_group(chat_type):
    return chat_type in ("group", "supergroup")

@dp.callback_query(F.data.startswith("game_"))
async def game_menu_cb(cb: CallbackQuery):
    game = cb.data[5:]
    if not is_group(cb.message.chat.type):
        await cb.answer("❌ Игры только в группах!", show_alert=True); return
    name, desc = GAME_INFO[game]
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"<b>{name}</b>\n\n{desc}\n\n💵 Ставка:", bet_kb(game))
    await cb.answer()

@dp.callback_query(F.data.startswith("bet_"))
async def bet_cb(cb: CallbackQuery):
    _, game, bet_str = cb.data.split("_", 2)
    bet = int(bet_str)
    if not is_group(cb.message.chat.type):
        await cb.answer("❌ Игры только в группах!", show_alert=True); return
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name)
    if user.get("banned"):
        await cb.answer("🚫 Забанен!", show_alert=True); return
    save_db(db); await cb.answer()
    if user["balance"] < bet:
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"❌ <b>Мало средств!</b>\n\nБаланс: <code>{fmt(user['balance'])}</code>\nСтавка: <code>{fmt(bet)}</code>",
            back_kb()); return
    if game == "football":     await start_football(cb, db, uid, bet)
    elif game == "mines":      await start_mines(cb, db, uid, bet)
    elif game == "basketball": await start_basketball(cb, db, uid, bet)
    elif game == "ttt":        await start_ttt(cb, db, uid, bet)

# ═══════════════════════════════════════════════════════════════════════════════
# ⚽ ФУТБОЛ
# ═══════════════════════════════════════════════════════════════════════════════
def football_kb():
    return kb([btn("⬅️ Влево","football_left",style="primary",icon=EI_LIKE),
               btn("⬆️ Центр","football_center",style="primary",icon=EI_OK),
               btn("➡️ Вправо","football_right",style="primary",icon=EI_LIKE)])

async def start_football(cb, db, uid, bet):
    sessions[uid] = {"game": "football", "bet": bet}
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"{ae('⚽',EI_OK)} <b>Пенальти!</b>\n\nСтавка: <code>{fmt(bet)}</code>\n\n🥅 Куда бьёшь?",
        football_kb())

@dp.callback_query(F.data.startswith("football_"))
async def football_shot_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); d = cb.data.split("_")[1]
    sess = sessions.pop(uid, None)
    if not sess: await cb.answer("Новая игра!", show_alert=True); return
    await cb.answer("⚽ Удар!"); bet = sess["bet"]
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name)
    gk = random.choice(["left","center","right"])
    dirs = {"left":"⬅️","center":"⬆️","right":"➡️"}
    win = d != gk
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"{ae('⚽',EI_OK)} <b>Мяч летит...</b>")
    await asyncio.sleep(1.2)
    if win:
        user["balance"] += bet; user["stats"]["wins"] += 1
        r = f"{ae('🎉',EI_OK)} <b>ГОЛ!</b> +<code>{fmt(bet)}</code>"
        add_log(db, uid, "football_win", f"+{fmt(bet)}")
    else:
        user["balance"] -= bet; user["stats"]["losses"] += 1
        r = f"{ae('🧤',EI_WARN)} <b>Поймал!</b> -<code>{fmt(bet)}</code>"
        add_log(db, uid, "football_loss", f"-{fmt(bet)}")
    save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"⚽ <b>Результат</b>\n\nТы: {dirs[d]} | Вратарь: {dirs[gk]}\n\n"
        f"{r}\n\n💰 <code>{fmt(user['balance'])}</code>", game_nav_kb("game_football"))

# ═══════════════════════════════════════════════════════════════════════════════
# 🏀 БАСКЕТБОЛ
# ═══════════════════════════════════════════════════════════════════════════════
def basketball_kb():
    return kb([btn("⬅️ Влево","bball_left",style="primary",icon=EI_LIKE),
               btn("⬆️ Центр","bball_center",style="primary",icon=EI_OK),
               btn("➡️ Вправо","bball_right",style="primary",icon=EI_LIKE)])

async def start_basketball(cb, db, uid, bet):
    sessions[uid] = {"game": "basketball", "bet": bet}
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"{ae('🏀',EI_OK)} <b>Штрафной!</b>\n\nСтавка: <code>{fmt(bet)}</code>\n\n🏀 Куда?",
        basketball_kb())

@dp.callback_query(F.data.startswith("bball_"))
async def bball_shot_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); d = cb.data.split("_")[1]
    sess = sessions.pop(uid, None)
    if not sess: await cb.answer("Новая игра!", show_alert=True); return
    await cb.answer("🏀 Бросок!"); bet = sess["bet"]
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name)
    df = random.choice(["left","center","right"])
    dirs = {"left":"⬅️","center":"⬆️","right":"➡️"}
    win = d != df
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"{ae('🏀',EI_OK)} <b>Мяч в воздухе...</b>")
    await asyncio.sleep(1.2)
    if win:
        user["balance"] += bet; user["stats"]["wins"] += 1
        r = f"{ae('🎉',EI_OK)} <b>Кольцо!</b> +<code>{fmt(bet)}</code>"
        add_log(db, uid, "basketball_win", f"+{fmt(bet)}")
    else:
        user["balance"] -= bet; user["stats"]["losses"] += 1
        r = f"{ae('🚫',EI_WARN)} <b>Промах!</b> -<code>{fmt(bet)}</code>"
        add_log(db, uid, "basketball_loss", f"-{fmt(bet)}")
    save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🏀 <b>Результат</b>\n\nТы: {dirs[d]} | Защитник: {dirs[df]}\n\n"
        f"{r}\n\n💰 <code>{fmt(user['balance'])}</code>", game_nav_kb("game_basketball"))

# ═══════════════════════════════════════════════════════════════════════════════
# 💣 МИНЫ
# ═══════════════════════════════════════════════════════════════════════════════
MINES_SAFE = 12

def mines_kb(revealed, mines, bet_val=None, dead=False, won=False):
    sym = {0:"⬛","safe":"💎","mine":"💥","hidden_mine":"💣"}
    rows = []
    for rs in range(0, 16, 4):
        row = []
        for i in range(rs, rs+4):
            if i in revealed:
                s = "mine" if i in mines else "safe"
                row.append({"text": sym[s], "callback_data": "noop"})
            elif dead and i in mines:
                row.append({"text": sym["hidden_mine"], "callback_data": "noop"})
            else:
                cd = "noop" if (dead or won) else f"mines_open_{i}"
                row.append({"text": sym[0], "callback_data": cd})
        rows.append(row)
    if dead or won:
        rows.append([btn("🔄 Ещё","game_mines",style="success",icon=EI_OK),
                     btn("🎮 Игры","cat_games",style="primary",icon=EI_LIKE)])
        rows.append([btn("🏠 Меню","main_menu",icon=EI_STAR)])
    else:
        prize = fmt(bet_val) if bet_val else "x2"
        rows.append([btn(f"✅ Забрать +{prize}","mines_cashout",style="success",icon=EI_OK)])
    return {"inline_keyboard": rows}

async def start_mines(cb, db, uid, bet):
    mines = set(random.sample(range(16), 4))
    sessions[uid] = {"game":"mines","bet":bet,"mines":list(mines),"revealed":[]}
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"{ae('💣',EI_WARN)} <b>Мины</b>\n\n"
        f"Ставка: <code>{fmt(bet)}</code> | Мин: 4/16\nПриз: x2\n\nОткрывай!",
        mines_kb([], mines, bet))

@dp.callback_query(F.data.startswith("mines_open_"))
async def mines_open_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); idx = int(cb.data.split("_")[2])
    sess = sessions.get(uid)
    if not sess or sess["game"] != "mines":
        await cb.answer("Новая игра!", show_alert=True); return
    await cb.answer()
    mines = set(sess["mines"]); revealed = sess["revealed"]; bet = sess["bet"]
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name)

    if idx in mines:
        revealed.append(idx)
        user["balance"] -= bet; user["stats"]["losses"] += 1
        add_log(db, uid, "mines_loss", f"-{fmt(bet)}")
        save_db(db); sessions.pop(uid)
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"{ae('💥',EI_WARN)} <b>БУМ!</b>\n\n-<code>{fmt(bet)}</code>\n\n"
            f"💰 <code>{fmt(user['balance'])}</code>",
            mines_kb(revealed, mines, bet, dead=True)); return

    revealed.append(idx)
    safe_opened = len([r for r in revealed if r not in mines])
    safe_left = MINES_SAFE - safe_opened

    if safe_left == 0:
        user["balance"] += bet; user["stats"]["wins"] += 1
        add_log(db, uid, "mines_win", f"+{fmt(bet)}")
        save_db(db); sessions.pop(uid)
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"{ae('🏆',EI_OK)} <b>Все открыты!</b>\n\n+<code>{fmt(bet)}</code>\n\n"
            f"💰 <code>{fmt(user['balance'])}</code>",
            mines_kb(revealed, mines, bet, won=True)); return

    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"💣 <b>Мины</b>\n\n💎 {safe_opened}/{MINES_SAFE} | ⬜ {safe_left}\n"
        f"💰 Приз: +<code>{fmt(bet)}</code>",
        mines_kb(revealed, mines, bet))

@dp.callback_query(F.data == "mines_cashout")
async def mines_cashout_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); sess = sessions.pop(uid, None)
    if not sess: await cb.answer("Нет игры!", show_alert=True); return
    await cb.answer("💰 Забрал!"); bet = sess["bet"]
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name)
    user["balance"] += bet; user["stats"]["wins"] += 1
    add_log(db, uid, "mines_cashout", f"+{fmt(bet)}"); save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"{ae('✅',EI_OK)} <b>Забрал!</b>\n\n+<code>{fmt(bet)}</code>\n\n"
        f"💰 <code>{fmt(user['balance'])}</code>", game_nav_kb("game_mines"))

# ═══════════════════════════════════════════════════════════════════════════════
# ❌⭕ КРЕСТИКИ-НОЛИКИ
# ═══════════════════════════════════════════════════════════════════════════════
SYM = {0:"⬜", 1:"❌", 2:"⭕"}

def ttt_kb(board, over=False):
    rows = []
    for rs in range(0, 9, 3):
        row = []
        for i in range(rs, rs+3):
            v = board[i]; cd = "noop" if (v or over) else f"ttt_move_{i}"
            row.append({"text": SYM[v], "callback_data": cd})
        rows.append(row)
    if over:
        rows.append([btn("🔄 Ещё","game_ttt",style="success",icon=EI_OK),
                     btn("🎮 Игры","cat_games",style="primary",icon=EI_LIKE)])
        rows.append([btn("🏠 Меню","main_menu",icon=EI_STAR)])
    return {"inline_keyboard": rows}

def ttt_winner(board):
    for a,b,c in [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]:
        if board[a] and board[a]==board[b]==board[c]: return board[a]
    return -1 if all(board) else 0

def bot_move(board):
    for i in range(9):
        if not board[i]:
            board[i]=2
            if ttt_winner(board)==2: return
            board[i]=0
    for i in range(9):
        if not board[i]:
            board[i]=1
            if ttt_winner(board)==1: board[i]=2; return
            board[i]=0
    if not board[4]: board[4]=2; return
    e=[i for i in range(9) if not board[i]]
    if e: board[random.choice(e)]=2

async def start_ttt(cb, db, uid, bet):
    board = [0]*9; sessions[uid] = {"game":"ttt","bet":bet,"board":board}
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"❌⭕ <b>Крестики</b>\n\nСтавка: <code>{fmt(bet)}</code>\nТы — ❌ | Бот — ⭕\n\nТвой ход!",
        ttt_kb(board))

@dp.callback_query(F.data.startswith("ttt_move_"))
async def ttt_move_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); idx = int(cb.data.split("_")[2])
    sess = sessions.get(uid)
    if not sess or sess["game"]!="ttt":
        await cb.answer("Новая игра!", show_alert=True); return
    board = sess["board"]; bet = sess["bet"]
    if board[idx]: await cb.answer("Занято!", show_alert=True); return
    await cb.answer(); board[idx] = 1
    w = ttt_winner(board)
    if not w: bot_move(board); w = ttt_winner(board)
    over = w != 0; db = load_db(); user = get_user(db, uid, cb.from_user.first_name)
    if w==1:
        user["balance"]+=bet; user["stats"]["wins"]+=1
        r=f"{ae('🏆',EI_OK)} <b>Победа!</b> +<code>{fmt(bet)}</code>"
        add_log(db,uid,"ttt_win",f"+{fmt(bet)}")
    elif w==2:
        user["balance"]-=bet; user["stats"]["losses"]+=1
        r=f"{ae('🤖',EI_WARN)} <b>Бот!</b> -<code>{fmt(bet)}</code>"
        add_log(db,uid,"ttt_loss",f"-{fmt(bet)}")
    elif w==-1:
        user["stats"]["draws"]+=1; r=f"{ae('🤝',EI_STAR)} <b>Ничья!</b>"
        add_log(db,uid,"ttt_draw","ничья")
    else: r=None
    if over: save_db(db); sessions.pop(uid,None)
    else: save_db(db)
    body = f"❌⭕ <b>Крестики</b>\n\nСтавка: <code>{fmt(bet)}</code>\nТы — ❌ | Бот — ⭕"
    if r: body += f"\n\n{r}\n\n💰 <code>{fmt(user['balance'])}</code>"
    else: body += "\n\nТвой ход!"
    await edit_msg(cb.message.chat.id, cb.message.message_id, body, ttt_kb(board, over))

# ─── NOOP ────────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "noop")
async def noop_cb(cb: CallbackQuery):
    await cb.answer()

# ─── UNKNOWN COMMAND ─────────────────────────────────────────────────────────
@dp.message(F.text.startswith("/"))
async def unknown_cmd(msg: Message):
    await send_msg(msg.chat.id,
        "Упс, неизвестная команда, используй команду /help")

# ─── MAIN ────────────────────────────────────────────────────────────────────
async def main():
    print("🎮 gamGems запущен!")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
