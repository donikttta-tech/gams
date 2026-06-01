import asyncio
import random
import json
import os
import html
import time
from datetime import date, datetime
from aiohttp import ClientSession

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ─── CONFIG ─────────────────────────────────────────────────────────────────
TOKEN = "8906467127:AAEXNVFAzDfR95fZwT7Fyn4wLEeRtKU5sL4"
DB_FILE = "users.json"
PROMO_FILE = "promos.json"
BUSINESS_FILE = "businesses.json"
ADMIN_ID = "8144110555"
CHANNEL = "@gamgems_chanell"

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ─── RAW TG API ─────────────────────────────────────────────────────────────
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

async def send_dice(chat_id, emoji):
    """Отправляет официальную Telegram-анимацию игры и возвращает ответ API.

    Для ⚽/🏀 Telegram сам рассчитывает value, по которому бот понимает:
    попал игрок или нет.
    """
    return await tg("sendDice", chat_id=chat_id, emoji=emoji)

def get_dice_value(resp):
    try:
        return int(resp.get("result", {}).get("dice", {}).get("value", 0))
    except Exception:
        return 0

async def send_stars_invoice(chat_id, stars):
    prices = [{"label": f"{stars} Telegram Stars", "amount": int(stars)}]
    currency_amount = int(stars) * SHOP_RATE_PER_STAR
    return await tg("sendInvoice",
        chat_id=chat_id,
        title="Покупка валюты gamGems",
        description=f"{stars} ⭐ = {fmt(currency_amount)}",
        payload=f"shop_stars_{stars}",
        provider_token="",
        currency="XTR",
        prices=prices,
        reply_markup={"inline_keyboard": [[{"text": f"Оплатить {stars} ⭐", "pay": True}]]})

async def send_business_stars_invoice(chat_id, key):
    cfg = BUSINESSES[key]
    stars = int(cfg["stars"])
    prices = [{"label": cfg["name"], "amount": stars}]
    return await tg("sendInvoice",
        chat_id=chat_id,
        title=f"Покупка бизнеса: {cfg['name']}",
        description=f"{cfg['name']} — {stars} ⭐",
        payload=f"biz_buy_{key}",
        provider_token="",
        currency="XTR",
        prices=prices,
        reply_markup={"inline_keyboard": [[{"text": f"Купить за {stars} ⭐", "pay": True}]]})

async def check_sub(user_id):
    try:
        r = await tg("getChatMember", chat_id=CHANNEL, user_id=int(user_id))
        s = r.get("result", {}).get("status", "")
        return s in ("member", "administrator", "creator")
    except:
        return True

# ─── PREMIUM EMOJI ──────────────────────────────────────────────────────────
EI_OK = "5310076249404621168"
EI_LIKE = "5285430309720966085"
EI_WARN = "5310169226856644648"
EI_STAR = "5285032475490273112"

def ae(emoji, eid):
    return f'<tg-emoji emoji-id="{eid}">{emoji}</tg-emoji>'

def safe(t):
    return html.escape(str(t))

# ─── BUTTON / KB ────────────────────────────────────────────────────────────
def btn(text, cb, style=None, icon=None):
    b = {"text": text, "callback_data": cb}
    if style: b["style"] = style
    if icon:  b["icon_custom_emoji_id"] = icon
    return b

def url_btn(text, url, style=None, icon=None):
    b = {"text": text, "url": url}
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

def get_user(db, uid, name="Игрок", username=""):
    if uid not in db:
        db[uid] = {
            "name": name, "username": username,
            "balance": 2_500_000, "promo_earnings": 0,
            "joined": str(date.today()), "last_bonus": None,
            "referrals": [], "referred_by": None,
            "verified": False, "banned": False,
            "stats": {"wins": 0, "losses": 0, "draws": 0},
            "transfer_count": {"date": "", "count": 0},
            "activated_promos": [], "created_promo": None,
            "user_logs": [],
        }
    else:
        db[uid]["name"] = name
        if username:
            db[uid]["username"] = username
    return db[uid]

def fmt(n):
    return "${:,.0f}".format(n).replace(",", ".")

def parse_amount(s):
    s = s.replace("$","").replace(".","").replace(",","").replace(" ","")
    return int(s) if s.isdigit() and int(s) > 0 else None

def add_log(db, uid, action, detail=""):
    if uid not in db: return
    logs = db[uid].get("user_logs", [])
    logs.insert(0, {"time": datetime.now().strftime("%d.%m %H:%M"),
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

# ─── BUSINESSES DB ──────────────────────────────────────────────────────────
def load_businesses():
    if os.path.exists(BUSINESS_FILE):
        with open(BUSINESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}
    now = int(time.time())
    changed = False
    for key in BUSINESSES:
        if key not in data:
            data[key] = {"owner_id": None, "owner_name": "", "last_claim": now,
                         "balance": 0, "sale_price": None}
            changed = True
        else:
            rec = data[key]
            rec.setdefault("owner_id", None)
            rec.setdefault("owner_name", "")
            rec.setdefault("last_claim", now)
            rec.setdefault("balance", 0)
            rec.setdefault("sale_price", None)
    if changed:
        save_businesses(data)
    return data

def save_businesses(data):
    with open(BUSINESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def business_pending_income(key, rec, now=None):
    now = int(now or time.time())
    pending = int(rec.get("balance", 0))
    hourly = int(BUSINESSES[key].get("hourly", 0))
    hours = 0
    if rec.get("owner_id") and hourly > 0:
        hours = max(0, (now - int(rec.get("last_claim", now))) // 3600)
        pending += hours * hourly
    return pending, hours

def add_business_income(key, amount):
    amount = int(amount)
    if amount <= 0 or key not in BUSINESSES:
        return
    data = load_businesses()
    rec = data.get(key, {})
    if not rec.get("owner_id"):
        return
    rec["balance"] = int(rec.get("balance", 0)) + amount
    save_businesses(data)

def add_business_loss_income(loss_amount):
    add_business_income("casino", int(loss_amount * 0.85))

def add_business_win_income(win_amount):
    add_business_income("computer_club", int(win_amount * 0.20))

def business_price_text(key):
    cfg = BUSINESSES[key]
    if "stars" in cfg:
        return f"{cfg['stars']} ⭐"
    return fmt(cfg["price"])

def business_base_price(key):
    cfg = BUSINESSES[key]
    if "price" in cfg:
        return int(cfg["price"])
    # Для бизнесов за Stars считаем стоимость по курсу магазина.
    return int(cfg.get("stars", 0) * SHOP_RATE_PER_STAR)

def business_state_sell_price(key):
    return business_base_price(key) // 2

def user_business_key(data, uid):
    uid = str(uid)
    for key, rec in data.items():
        if str(rec.get("owner_id")) == uid:
            return key
    return None

def user_has_business(data, uid):
    return user_business_key(data, uid) is not None

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

class BetStates(StatesGroup):
    waiting_amount = State()

class BusinessStates(StatesGroup):
    waiting_sell_price = State()

class AdminStates(StatesGroup):
    broadcast = State()
    target_id = State()
    amount = State()
    promo_code = State()
    promo_amount = State()
    promo_activations = State()
    business_key = State()

# ─── SESSIONS ───────────────────────────────────────────────────────────────
sessions = {}
captcha_data = {}

# ─── LIMITS / ECONOMY ───────────────────────────────────────────────────────
CUSTOM_BET_MAX = 1_500_000
DUEL_MAX_BET = 50_000_000
PROMO_USER_REWARD = 10_000_000
PROMO_CREATOR_REWARD = 500_000
SHOP_RATE_PER_STAR = 1_500_000
SHOP_STAR_PACKS = [1, 5, 10, 25, 50, 100]

BUSINESSES = {
    "bakery": {"name": "Пекарня", "price": 50_000_000, "hourly": 500_000,
               "desc": "доход 500.000 в час"},
    "burger": {"name": "Бургер Кинг", "price": 100_000_000, "hourly": 1_500_000,
               "desc": "доход 1.500.000 в час"},
    "bank": {"name": "Спермо Банк", "price": 200_000_000, "hourly": 5_000_000,
             "desc": "доход 5.000.000 в час"},
    "computer_club": {"name": "Компьютерный клуб", "price": 500_000_000, "hourly": 0,
                      "desc": "20% от выигрышей в дуэлях и минах"},
    "casino": {"name": "Казино", "stars": 50, "hourly": 0,
               "desc": "85% от всех проигрышей во всех играх"},
}

pending_duels = {}
pending_duel_tasks = {}
duel_games = {}
duel_player_map = {}
duel_turn_tasks = {}
duel_counter = 0
DUEL_TIMEOUT = 300  # 5 минут на принятие заявки и на каждый ход

# ─── KEYBOARDS ──────────────────────────────────────────────────────────────
def sub_kb():
    return kb(
        [url_btn("📢 Подписаться", "https://t.me/gamgems_chanell", style="primary", icon=EI_OK)],
        [btn("✅ Проверить", "check_sub", style="success", icon=EI_OK)])

def main_menu_kb(is_admin=False):
    rows = [
        [btn("🎮 Игры", "cat_games", style="success", icon=EI_OK),
         btn("🎁 Бонусы", "cat_bonus", style="success", icon=EI_OK)],
        [btn("🏢 Бизнесы", "cat_businesses", style="success", icon=EI_OK),
         btn("🛒 Магазин", "cat_shop", style="success", icon=EI_OK)],
        [btn("📊 Инфо", "cat_info", style="primary", icon=EI_LIKE),
         btn("🏆 Рейтинг", "cat_rating", style="primary", icon=EI_LIKE)],
        [btn("🎟️ Промокоды", "cat_promo", style="primary", icon=EI_STAR)],
    ]
    if is_admin:
        rows.append([btn("🛠️ Админ", "admin_panel", style="danger", icon=EI_WARN)])
    return {"inline_keyboard": rows}

def games_kb():
    return kb(
        [btn("⚽  Футбол — x2", "game_football", style="success", icon=EI_OK),
         btn("🏀  Баскетбол — x2", "game_basketball", style="success", icon=EI_OK)],
        [btn("🎯  Дартс", "game_darts", style="success", icon=EI_OK),
         btn("🎰  Слоты", "game_slots", style="danger", icon=EI_WARN)],
        [btn("💣  Мины", "game_mines", style="danger", icon=EI_WARN),
         btn("📈  Краш", "game_crash", style="danger", icon=EI_WARN)],
        [btn("🃏  21 Очко", "game_blackjack", style="primary", icon=EI_STAR),
         btn("🏆  Золото", "game_gold", style="primary", icon=EI_STAR)],
        [btn("⚔️  Дуэль — TTT x2", "game_duel_info", style="primary", icon=EI_LIKE)],
        [btn("🔙  Меню", "main_menu", icon=EI_STAR)])

def bonus_kb():
    return kb(
        [btn("🎁  Бонус", "daily_bonus", style="success", icon=EI_OK)],
        [btn("👥  Рефералы", "referral", style="primary", icon=EI_LIKE)],
        [btn("🔙  Меню", "main_menu", icon=EI_STAR)])

def info_kb():
    return kb(
        [btn("💰  Баланс", "balance", style="success", icon=EI_OK)],
        [btn("📊  Статистика", "stats", style="primary", icon=EI_LIKE)],
        [btn("🔙  Меню", "main_menu", icon=EI_STAR)])

def rating_kb():
    return kb(
        [btn("💰  Баланс", "rating_balance", style="success", icon=EI_OK)],
        [btn("🏆  Победы", "rating_wins", style="primary", icon=EI_LIKE)],
        [btn("💀  Поражения", "rating_losses", style="danger", icon=EI_WARN)],
        [btn("🔙  Меню", "main_menu", icon=EI_STAR)])

def promo_kb():
    return kb(
        [btn("🎟️  Ввести промокод", "promo_enter", style="success", icon=EI_OK)],
        [btn("👤  Промо пользователя", "promo_user_enter", style="primary", icon=EI_LIKE)],
        [btn("➕  Создать свой", "promo_create", style="success", icon=EI_OK)],
        [btn("📋  Мой промокод", "promo_my", style="primary", icon=EI_STAR)],
        [btn("🔙  Меню", "main_menu", icon=EI_STAR)])

def shop_kb():
    rows = []
    for i in range(0, len(SHOP_STAR_PACKS), 2):
        row = []
        for stars in SHOP_STAR_PACKS[i:i+2]:
            row.append(btn(f"⭐ {stars} → {fmt(stars * SHOP_RATE_PER_STAR)}", f"shop_buy_{stars}", style="success", icon=EI_OK))
        rows.append(row)
    rows.append([btn("🔙  Меню", "main_menu", icon=EI_STAR)])
    return {"inline_keyboard": rows}

def businesses_kb(uid):
    data = load_businesses()
    rows = []
    has_biz = user_has_business(data, uid)
    for key, cfg in BUSINESSES.items():
        rec = data[key]
        owner_id = rec.get("owner_id")
        sale_price = rec.get("sale_price")
        if owner_id == uid:
            # FIX: если уже выставлен на продажу — даём кнопку «Снять с продажи»
            if sale_price:
                sell_btn = btn(f"❎ Снять с продажи ({fmt(sale_price)})", f"biz_sell_cancel_{key}", style="danger", icon=EI_WARN)
            else:
                sell_btn = btn("🏷 Игроку", f"biz_sell_select_{key}", style="primary", icon=EI_STAR)
            rows.append([btn(f"💰 Доход: {cfg['name']}", f"biz_claim_{key}", style="success", icon=EI_OK),
                         sell_btn,
                         btn("🏛 В госс", f"biz_sell_state_{key}", style="danger", icon=EI_WARN)])
        elif not has_biz and sale_price:
            rows.append([btn(f"🛒 Купить {cfg['name']} за {fmt(sale_price)}", f"biz_buy_sale_{key}", style="success", icon=EI_OK)])
        elif not has_biz and not owner_id:
            rows.append([btn(f"🛒 Купить {cfg['name']} — {business_price_text(key)}", f"biz_buy_{key}", style="success", icon=EI_OK)])
    if has_biz:
        rows.append([btn("ℹ️ У тебя уже есть бизнес", "noop", style="primary", icon=EI_STAR)])
    rows.append([btn("🔄 Обновить", "cat_businesses", style="primary", icon=EI_LIKE),
                 btn("🏠 Меню", "main_menu", icon=EI_STAR)])
    return {"inline_keyboard": rows}

def sellbiz_choose_kb(uid):
    data = load_businesses(); rows = []
    for key, cfg in BUSINESSES.items():
        if data[key].get("owner_id") == uid:
            rows.append([btn(f"🏷 {cfg['name']}", f"biz_sell_select_{key}", style="primary", icon=EI_STAR)])
    rows.append([btn("❌ Отмена", "cancel_fsm", style="danger", icon=EI_WARN)])
    return {"inline_keyboard": rows}

def businesses_text(uid):
    data = load_businesses()
    lines = ["🏢 <b>БИЗНЕСЫ</b>\n"]
    for key, cfg in BUSINESSES.items():
        rec = data[key]
        owner = rec.get("owner_name") or "—"
        if rec.get("owner_id"):
            status = f"👤 Куплен: <b>{safe(owner)}</b>"
            if rec.get("sale_price"):
                status += f"\n🏷 Продаётся: <code>{fmt(rec['sale_price'])}</code>"
            if rec.get("owner_id") == uid:
                pending, hours = business_pending_income(key, rec)
                status += f"\n💰 Доступно: <code>{fmt(pending)}</code>"
        else:
            status = "🟢 Свободен"
        lines.append(
            f"<b>{cfg['name']}</b> — <code>{business_price_text(key)}</code>\n"
            f"<i>{cfg['desc']}</i>\n{status}\n")
    lines.append("<i>/sellbiz — выставить свой бизнес на продажу</i>")
    return "\n".join(lines)

def admin_business_choose_kb(action, target_id):
    data = load_businesses(); rows = []
    for key, cfg in BUSINESSES.items():
        if action == "give_business" and data[key].get("owner_id"):
            continue
        if action == "take_business" and data[key].get("owner_id") != target_id:
            continue
        rows.append([btn(f"🏢 {cfg['name']}", f"admin_biz_{action}_{target_id}_{key}", style="primary", icon=EI_STAR)])
    rows.append([btn("❌ Отмена", "cancel_fsm", style="danger", icon=EI_WARN)])
    return {"inline_keyboard": rows}

def admin_kb():
    return kb(
        [btn("📢  Рассылка", "admin_broadcast", style="danger", icon=EI_WARN),
         btn("🔨  Бан/Разбан", "admin_ban_unban", style="danger", icon=EI_WARN)],
        [btn("💰  Баланс игрока", "admin_check_balance", style="primary", icon=EI_LIKE),
         btn("📋  Логи", "admin_logs", style="primary", icon=EI_LIKE)],
        [btn("💸  Выдать $", "admin_give", style="success", icon=EI_OK),
         btn("📥  Забрать $", "admin_take", style="danger", icon=EI_WARN)],
        [btn("🎟️  Создать промо", "admin_create_promo", style="success", icon=EI_OK),
         btn("🗑️  Обнулить", "admin_reset", style="danger", icon=EI_WARN)],
        [btn("🏢 Выдать бизнес", "admin_give_business", style="success", icon=EI_OK),
         btn("📥 Забрать бизнес", "admin_take_business", style="danger", icon=EI_WARN)],
        [btn("🔙  Меню", "main_menu", icon=EI_STAR)])

def back_kb():
    return kb([btn("🔙  Меню", "main_menu", icon=EI_STAR)])

def cancel_kb():
    return kb([btn("❌  Отмена", "cancel_fsm", style="danger", icon=EI_WARN)])

def back_promo_kb():
    return kb([btn("🔙  Промокоды", "cat_promo", style="primary", icon=EI_STAR),
               btn("🏠  Меню", "main_menu", icon=EI_STAR)])

def game_nav_kb(cb):
    return kb(
        [btn("🔄  Ещё", cb, style="success", icon=EI_OK),
         btn("🎮  Игры", "cat_games", style="primary", icon=EI_LIKE)],
        [btn("🏠  Меню", "main_menu", icon=EI_STAR)])

def bet_kb(game):
    bets = [100_000, 250_000, 500_000, 1_000_000, CUSTOM_BET_MAX]
    rows = []
    for i in range(0, len(bets), 2):
        row = [btn(f"💵 {fmt(bets[j])}", f"bet_{game}_{bets[j]}",
                   style="success", icon=EI_OK) for j in range(i, min(i+2, len(bets)))]
        rows.append(row)
    rows.append([btn(f"✍️ Своя ставка до {fmt(CUSTOM_BET_MAX)}", f"custom_bet_{game}", style="primary", icon=EI_STAR)])
    rows.append([btn("🔙  Меню", "main_menu", icon=EI_STAR)])
    return {"inline_keyboard": rows}

# ─── TEXT ────────────────────────────────────────────────────────────────────
def main_menu_text(name, user):
    s = user["stats"]
    bonus = "✅ Получен" if user["last_bonus"] == str(date.today()) else f"{ae('🎁', EI_OK)} Доступен"
    return (
        f"<b>gamGems</b>\n\n"
        f"👤 <b>{safe(name)}</b>\n"
        f"💰 Баланс: <code>{fmt(user['balance'])}</code>\n"
        f"{bonus}\n\n"
        f"🏆 Побед: <b>{s['wins']}</b>  |  💀 Поражений: <b>{s['losses']}</b>\n\n"
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
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        main_menu_text(cb.from_user.first_name, user),
        main_menu_kb(is_admin=(uid == ADMIN_ID)))
    await cb.answer("❌ Отменено")

# ─── /start ─────────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(msg: Message):
    db = load_db(); uid = str(msg.from_user.id)
    name = msg.from_user.first_name or "Игрок"
    uname = msg.from_user.username or ""
    user = get_user(db, uid, name, uname)

    pending_ref = None
    args = msg.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        pending_ref = args[1][4:]

    # В группе — автоверификация, без проверки подписки
    if msg.chat.type in ("group", "supergroup"):
        user["verified"] = True
        save_db(db)
        await send_msg(msg.chat.id,
            main_menu_text(name, user),
            main_menu_kb(is_admin=(uid == ADMIN_ID)))
        return

    # В ЛС — капча → подписка → меню
    if not user["verified"]:
        q, ans, opts = make_captcha()
        captcha_data[uid] = {"ans": ans, "pending_ref": pending_ref}
        save_db(db)
        await send_msg(msg.chat.id,
            f"🤖 <b>Докажи, что ты не бот!</b>\n\nРеши: <b>{q}</b>", captcha_kb(opts))
        return

    if not await check_sub(uid):
        save_db(db)
        await send_msg(msg.chat.id,
            f"📢 <b>Подпишись на канал!</b>\n\nДля использования бота нужно быть подписанным.",
            sub_kb())
        return

    if user.get("banned"):
        save_db(db)
        await send_msg(msg.chat.id, "🚫 Заблокирован!"); return

    save_db(db)
    await send_msg(msg.chat.id, main_menu_text(name, user),
        main_menu_kb(is_admin=(uid == ADMIN_ID)))

# ─── CHECK SUB CALLBACK ─────────────────────────────────────────────────────
@dp.callback_query(F.data == "check_sub")
async def check_sub_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id)
    if not await check_sub(uid):
        await cb.answer("❌ Ты не подписан!", show_alert=True); return
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    if user.get("banned"):
        await cb.answer("🚫 Заблокирован!", show_alert=True); return
    save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        main_menu_text(cb.from_user.first_name, user),
        main_menu_kb(is_admin=(uid == ADMIN_ID)))
    await cb.answer("✅ Подписка подтверждена!")

# ─── /help ──────────────────────────────────────────────────────────────────
@dp.message(Command("help"))
async def cmd_help(msg: Message):
    await send_msg(msg.chat.id,
        "<b>📖 Команды gamGems:</b>\n\n"
        "🎮 <b>Игры</b> (в группах и ЛС):\n"
        "   ⚽ Футбол, 💣 Мины, 🏀 Баскетбол, 🎰 Слоты, 🎯 Дартс, 📈 Краш, 🃏 21, 🏆 Золото\n\n"
        "⚔️ <b>/duel @user ставка</b> — TTT vs игрок\n"
        "💰 <b>б</b> — баланс (без /)\n"
        "💸 <b>/pay сумма ID</b> — перевод (20%, 2/день)\n"
        "   <i>/pay 1000000 123456789</i>\n"
        "   <i>Reply + /pay 1000000</i>\n"
        "🎁 Бонус — $1.000.000/день\n"
        "👥 Рефералы — $5.000.000/друг\n"
        "🎟️ Промокоды — вводи и создавай\n"
        "🏆 Рейтинг — топ игроков")

# ─── «б» — баланс без слеша ─────────────────────────────────────────────────
@dp.message(F.text.lower().in_(["б", "b"]))
async def cmd_bal_text(msg: Message):
    db = load_db(); uid = str(msg.from_user.id)
    user = get_user(db, uid, msg.from_user.first_name, msg.from_user.username or "")
    save_db(db)
    await send_msg(msg.chat.id, f"💰 <b>Баланс:</b> <code>{fmt(user['balance'])}</code>")

# ─── /pay ───────────────────────────────────────────────────────────────────
async def do_pay(src, db, uid, target_id, amount):
    user = db[uid]
    if not can_transfer(user): return False, "❌ Лимит 2 перевода/день!"
    if target_id == uid: return False, "❌ Нельзя себе!"
    if target_id not in db or not db[target_id].get("verified"): return False, "❌ Не найден!"
    if db[target_id].get("banned"): return False, "❌ Заблокирован!"
    if user["balance"] < amount: return False, f"❌ Мало средств!\nБаланс: <code>{fmt(user['balance'])}</code>"
    received = int(amount * 0.8); commission = amount - received
    user["balance"] -= amount; db[target_id]["balance"] += received
    did_transfer(user)
    tname = db[target_id].get("name", "Игрок")
    add_log(db, uid, "transfer", f"-{fmt(amount)} → {safe(tname)}")
    add_log(db, target_id, "transfer_in", f"+{fmt(received)} ← {safe(src.from_user.first_name)}")
    try:
        await send_msg(int(target_id),
            f"💸 <b>Перевод!</b>\n\nОт: <b>{safe(src.from_user.first_name)}</b>\n"
            f"💰 +<code>{fmt(received)}</code>\n\nБаланс: <code>{fmt(db[target_id]['balance'])}</code>")
    except: pass
    return True, (
        f"✅ <b>Перевод!</b>\n\n👤 <b>{safe(tname)}</b>\n"
        f"💰 Отправлено: <code>{fmt(amount)}</code>\n"
        f"📊 Комиссия: <code>{fmt(commission)}</code>\n"
        f"📬 Доставлено: <code>{fmt(received)}</code>\n\n"
        f"Баланс: <code>{fmt(user['balance'])}</code>")

@dp.message(Command("pay"))
async def cmd_pay(msg: Message, state: FSMContext):
    db = load_db(); uid = str(msg.from_user.id)
    user = get_user(db, uid, msg.from_user.first_name, msg.from_user.username or "")
    if not user.get("verified"): await send_msg(msg.chat.id, "❌ /start"); return
    if user.get("banned"): await send_msg(msg.chat.id, "🚫 Бан!"); return
    save_db(db)
    parts = msg.text.split()

    if len(parts) >= 3:
        amount = parse_amount(parts[1])
        tid = parts[2]
        if not amount: await send_msg(msg.chat.id, "❌ Неверная сумма!"); return
        if not tid.isdigit(): await send_msg(msg.chat.id, "❌ ID — число!"); return
        db = load_db()
        ok, text = await do_pay(msg, db, uid, tid, amount)
        if ok: save_db(db)
        await send_msg(msg.chat.id, text); return

    if len(parts) == 2 and msg.reply_to_message:
        amount = parse_amount(parts[1])
        if not amount: await send_msg(msg.chat.id, "❌ Неверная сумма!"); return
        tid = str(msg.reply_to_message.from_user.id)
        db = load_db()
        ok, text = await do_pay(msg, db, uid, tid, amount)
        if ok: save_db(db)
        await send_msg(msg.chat.id, text); return

    await state.set_state(PayStates.waiting_id)
    await send_msg(msg.chat.id,
        f"💸 <b>Перевод</b>\n\n💰 <code>{fmt(user['balance'])}</code>\n"
        f"📊 Комиссия 20% | Лимит 2/день\n\n👤 ID получателя:",
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
        f"✅ <b>{safe(db[txt]['name'])}</b>\n\n💰 Сумма:", cancel_kb())

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

# ─── /duel ──────────────────────────────────────────────────────────────────
@dp.message(Command("duel"))
async def cmd_duel(msg: Message):
    parts = msg.text.split()
    if len(parts) < 3:
        await send_msg(msg.chat.id,
            "⚔️ <b>Дуэль — Крестики-нолики</b>\n\n"
            "<b>/duel @username ставка</b>\n"
            "<b>/duel ID ставка</b>\n\n"
            "<i>Пример: /duel @player 1000000</i>"); return

    target = parts[1]
    amount = parse_amount(parts[2])
    if not amount:
        await send_msg(msg.chat.id, "❌ Неверная сумма!"); return
    if amount > DUEL_MAX_BET:
        await send_msg(msg.chat.id, f"❌ Максимальная ставка в дуэли: <code>{fmt(DUEL_MAX_BET)}</code>"); return

    db = load_db(); uid = str(msg.from_user.id)
    user = get_user(db, uid, msg.from_user.first_name, msg.from_user.username or "")
    if not user.get("verified"):
        await send_msg(msg.chat.id, "❌ Напиши боту /start в ЛС"); return
    if user.get("banned"):
        await send_msg(msg.chat.id, "🚫 Бан!"); return
    if user["balance"] < amount:
        await send_msg(msg.chat.id, "❌ Недостаточно средств!"); return
    if uid in duel_player_map:
        await send_msg(msg.chat.id, "❌ Ты уже в дуэли!"); return
    if uid in sessions:
        await send_msg(msg.chat.id, "❌ Закончи текущую игру!"); return
    save_db(db)

    target_id = None
    if target.startswith("@"):
        uname = target[1:].lower()
        for tid, u in db.items():
            if u.get("username", "").lower() == uname:
                target_id = tid; break
    elif target.isdigit():
        target_id = target

    if not target_id or target_id == uid:
        await send_msg(msg.chat.id, "❌ Игрок не найден!"); return
    if target_id not in db or not db[target_id].get("verified"):
        await send_msg(msg.chat.id, "❌ Игрок не в боте!"); return
    if db[target_id].get("banned"):
        await send_msg(msg.chat.id, "❌ Игрок забанен!"); return
    if target_id in duel_player_map or target_id in pending_duels:
        await send_msg(msg.chat.id, "❌ Игрок занят!"); return
    if db[target_id]["balance"] < amount:
        await send_msg(msg.chat.id, "❌ У игрока мало средств!"); return

    pending_duels[target_id] = {"from_uid": uid, "from_name": msg.from_user.first_name, "bet": amount}
    pending_duel_tasks[target_id] = asyncio.create_task(expire_pending_duel(target_id, uid))

    try:
        await send_msg(int(target_id),
            f"⚔️ <b>Вызов на дуэль!</b>\n\n"
            f"👤 <b>{safe(msg.from_user.first_name)}</b> вызывает тебя!\n"
            f"💰 Ставка: <code>{fmt(amount)}</code>",
            kb([btn("⚔️ Принять", f"duel_accept_{uid}", style="success", icon=EI_OK),
                btn("❌ Отклонить", f"duel_decline_{uid}", style="danger", icon=EI_WARN)]))
    except:
        pending_duels.pop(target_id, None)
        t = pending_duel_tasks.pop(target_id, None)
        if t: t.cancel()
        await send_msg(msg.chat.id, "❌ Не удалось (игрок не запускал бота)"); return

    await send_msg(msg.chat.id,
        f"✅ Вызов отправлен <b>{safe(db[target_id].get('name',''))}</b>!\n"
        f"💰 Ставка: <code>{fmt(amount)}</code>")

@dp.callback_query(F.data.startswith("duel_accept_"))
async def duel_accept_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id)
    from_uid = cb.data.split("_")[2]
    pending = pending_duels.pop(uid, None)
    t = pending_duel_tasks.pop(uid, None)
    if t: t.cancel()
    if not pending or pending["from_uid"] != from_uid:
        await cb.answer("Вызов не найден!", show_alert=True); return

    bet = pending["bet"]; db = load_db()
    user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    from_user = get_user(db, from_uid, pending["from_name"])
    if user["balance"] < bet or from_user["balance"] < bet:
        save_db(db)
        await edit_msg(cb.message.chat.id, cb.message.message_id, "❌ У кого-то мало средств!")
        await cb.answer("Недостаточно средств!"); return

    user["balance"] -= bet; from_user["balance"] -= bet; save_db(db)

    global duel_counter; duel_counter += 1; gid = str(duel_counter)
    duel_games[gid] = {"players": [from_uid, uid], "bet": bet, "board": [0]*9, "turn": 0, "msgs": {}}
    duel_player_map[from_uid] = gid; duel_player_map[uid] = gid

    await edit_msg(cb.message.chat.id, cb.message.message_id, "✅ Дуэль начата!")

    r1 = await send_msg(int(from_uid),
        f"⚔️ <b>Дуэль vs {safe(cb.from_user.first_name)}</b>\n"
        f"💰 <code>{fmt(bet)}</code> | Ты — ❌\n\nТвой ход!",
        duel_ttt_active_kb([0]*9))
    if r1.get("result"):
        duel_games[gid]["msgs"][from_uid] = {"chat_id": int(from_uid), "msg_id": r1["result"]["message_id"]}

    r2 = await send_msg(int(uid),
        f"⚔️ <b>Дуэль vs {safe(pending['from_name'])}</b>\n"
        f"💰 <code>{fmt(bet)}</code> | Ты — ⭕\n\nЖдём ход противника...",
        duel_ttt_wait_kb([0]*9))
    if r2.get("result"):
        duel_games[gid]["msgs"][uid] = {"chat_id": int(uid), "msg_id": r2["result"]["message_id"]}
    schedule_duel_turn_timeout(gid)
    await cb.answer("⚔️ Дуэль начата!")

@dp.callback_query(F.data.startswith("duel_decline_"))
async def duel_decline_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); from_uid = cb.data.split("_")[2]
    pending = pending_duels.pop(uid, None)
    t = pending_duel_tasks.pop(uid, None)
    if t: t.cancel()
    if not pending or pending["from_uid"] != from_uid:
        await cb.answer("Не найден!", show_alert=True); return
    await edit_msg(cb.message.chat.id, cb.message.message_id, "❌ Отклонено.")
    try: await send_msg(int(from_uid), f"❌ <b>{safe(cb.from_user.first_name)}</b> отклонил дуэль")
    except: pass
    await cb.answer("Отклонено")

def duel_ttt_active_kb(board):
    sm = {0:"⬜", 1:"❌", 2:"⭕"}; rows = []
    for rs in range(0, 9, 3):
        row = [{"text": sm[board[i]], "callback_data": "noop" if board[i] else f"dmove_{i}"} for i in range(rs, rs+3)]
        rows.append(row)
    rows.append([btn("⏳ Твой ход!", "noop", style="success", icon=EI_OK)])
    return {"inline_keyboard": rows}

def duel_ttt_wait_kb(board):
    sm = {0:"⬜", 1:"❌", 2:"⭕"}; rows = []
    for rs in range(0, 9, 3):
        row = [{"text": sm[board[i]], "callback_data": "noop"} for i in range(rs, rs+3)]
        rows.append(row)
    rows.append([btn("⏳ Ход противника...", "noop")])
    return {"inline_keyboard": rows}

def duel_ttt_over_kb(board):
    sm = {0:"⬜", 1:"❌", 2:"⭕"}; rows = []
    for rs in range(0, 9, 3):
        row = [{"text": sm[board[i]], "callback_data": "noop"} for i in range(rs, rs+3)]
        rows.append(row)
    rows.append([btn("🏠 Меню", "main_menu", icon=EI_STAR)])
    return {"inline_keyboard": rows}

def ttt_winner(board):
    for a, b, c in [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]:
        if board[a] and board[a] == board[b] == board[c]: return board[a]
    return -1 if all(board) else 0

async def expire_pending_duel(target_id, from_uid):
    await asyncio.sleep(DUEL_TIMEOUT)
    pending = pending_duels.get(target_id)
    if not pending or pending.get("from_uid") != from_uid:
        return
    pending_duels.pop(target_id, None)
    pending_duel_tasks.pop(target_id, None)
    try: await send_msg(int(target_id), "⌛ <b>Вызов на дуэль истёк.</b>\n\nЗаявка не была принята за 5 минут.")
    except: pass
    try: await send_msg(int(from_uid), "⌛ <b>Дуэль отменена.</b>\n\nИгрок не принял заявку за 5 минут.")
    except: pass

async def finish_duel_timeout(gid, inactive_uid):
    g = duel_games.get(gid)
    if not g or inactive_uid not in g["players"]:
        return
    if g["players"][g["turn"]] != inactive_uid:
        return
    won_uid = g["players"][0] if g["players"][1] == inactive_uid else g["players"][1]
    lose_uid = inactive_uid
    bet = g["bet"]; board = g["board"]
    db = load_db()
    for puid in g["players"]: get_user(db, puid)
    db[won_uid]["balance"] += bet * 2; db[won_uid]["stats"]["wins"] += 1
    db[lose_uid]["stats"]["losses"] += 1
    add_log(db, won_uid, "duel_timeout_win", f"payout={fmt(bet * 2)}")
    add_log(db, lose_uid, "duel_timeout_loss", f"-{fmt(bet)}")
    add_business_win_income(bet * 2); add_business_loss_income(bet)
    save_db(db)
    for puid in g["players"]:
        msgs = g["msgs"].get(puid)
        if not msgs: continue
        if puid == won_uid:
            txt = f"🏆 <b>Победа!</b>\n\nПротивник бездействовал.\nВыплата x2: +<code>{fmt(bet * 2)}</code>\n\n💰 <code>{fmt(db[puid]['balance'])}</code>"
        else:
            txt = f"💀 <b>Поражение</b>\n\nТы бездействовал больше 5 минут.\n-<code>{fmt(bet)}</code>\n\n💰 <code>{fmt(db[puid]['balance'])}</code>"
        await edit_msg(msgs["chat_id"], msgs["msg_id"], txt, duel_ttt_over_kb(board))
    for puid in g["players"]: duel_player_map.pop(puid, None)
    duel_games.pop(gid, None)
    duel_turn_tasks.pop(gid, None)

def schedule_duel_turn_timeout(gid):
    old = duel_turn_tasks.pop(gid, None)
    if old: old.cancel()
    g = duel_games.get(gid)
    if not g: return
    uid = g["players"][g["turn"]]
    async def runner():
        await asyncio.sleep(DUEL_TIMEOUT)
        await finish_duel_timeout(gid, uid)
    duel_turn_tasks[gid] = asyncio.create_task(runner())

@dp.callback_query(F.data.startswith("dmove_"))
async def duel_move_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); idx = int(cb.data.split("_")[1])
    gid = duel_player_map.get(uid)
    if not gid: await cb.answer("Нет игры!", show_alert=True); return
    g = duel_games.get(gid)
    if not g: await cb.answer("Нет игры!", show_alert=True); return
    if g["players"][g["turn"]] != uid: await cb.answer("Не твой ход!", show_alert=True); return
    board = g["board"]
    if board[idx]: await cb.answer("Занято!", show_alert=True); return

    player_idx = g["players"].index(uid)
    board[idx] = 1 if player_idx == 0 else 2

    w = ttt_winner(board)
    if w:
        db = load_db()
        for puid in g["players"]: get_user(db, puid)
        bet = g["bet"]
        if w == -1:
            for puid in g["players"]:
                db[puid]["balance"] += bet
                add_log(db, puid, "duel_draw", "ставка вернулась")
        else:
            won_uid = g["players"][0] if w == 1 else g["players"][1]
            lose_uid = g["players"][1] if w == 1 else g["players"][0]
            db[won_uid]["balance"] += bet * 2; db[won_uid]["stats"]["wins"] += 1
            db[lose_uid]["stats"]["losses"] += 1
            add_log(db, won_uid, "duel_win", f"+{fmt(bet)}")
            add_log(db, lose_uid, "duel_loss", f"-{fmt(bet)}")
            add_business_win_income(bet * 2)
            add_business_loss_income(bet)
        save_db(db)
        t = duel_turn_tasks.pop(gid, None)
        if t: t.cancel()
        for puid in g["players"]:
            msgs = g["msgs"].get(puid)
            if not msgs: continue
            if w == -1: txt = f"🤝 <b>Ничья!</b>\n\n<code>{fmt(bet)}</code> возвращён\n\n💰 <code>{fmt(db[puid]['balance'])}</code>"
            elif puid == won_uid: txt = f"🏆 <b>Победа!</b>\n\nВыплата x2: +<code>{fmt(bet * 2)}</code>\n\n💰 <code>{fmt(db[puid]['balance'])}</code>"
            else: txt = f"💀 <b>Поражение</b>\n\n-<code>{fmt(bet)}</code>\n\n💰 <code>{fmt(db[puid]['balance'])}</code>"
            await edit_msg(msgs["chat_id"], msgs["msg_id"], txt, duel_ttt_over_kb(board))
        for puid in g["players"]: duel_player_map.pop(puid, None)
        duel_games.pop(gid, None)
        await cb.answer("Игра окончена!")
    else:
        g["turn"] = 1 - player_idx; opp_uid = g["players"][1 - player_idx]
        await edit_msg(cb.message.chat.id, cb.message.message_id, "⏳ Ход противника...", duel_ttt_wait_kb(board))
        opp_msgs = g["msgs"].get(opp_uid)
        opp_sym = "⭕" if 1 - player_idx == 1 else "❌"
        if opp_msgs:
            await edit_msg(opp_msgs["chat_id"], opp_msgs["msg_id"], f"⚔️ <b>Твой ход!</b> ({opp_sym})", duel_ttt_active_kb(board))
        g["msgs"][uid] = {"chat_id": cb.message.chat.id, "msg_id": cb.message.message_id}
        schedule_duel_turn_timeout(gid)
        await cb.answer("Ход!")

# ─── CAPTCHA CALLBACK ───────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("captcha_"))
async def captcha_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); chosen = int(cb.data.split("_")[1])
    data = captcha_data.get(uid, {})
    if chosen != data.get("ans"):
        q, ans, opts = make_captcha()
        captcha_data[uid] = {"ans": ans, "pending_ref": data.get("pending_ref")}
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"❌ <b>Неверно!</b>\n\nРеши: <b>{q}</b>", captcha_kb(opts))
        await cb.answer("Неверно!"); return

    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    user["verified"] = True
    ref_id = data.get("pending_ref")
    if ref_id and ref_id != uid and ref_id in db:
        if uid not in db[ref_id]["referrals"]:
            db[ref_id]["referrals"].append(uid); db[ref_id]["balance"] += 5_000_000
            user["referred_by"] = ref_id
            try: await send_msg(int(ref_id), f"🎉 Новый игрок!\n💰 <b>+{fmt(5_000_000)}</b>")
            except: pass
    save_db(db); captcha_data.pop(uid, None)

    if not await check_sub(uid):
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            "📢 <b>Подпишись на канал!</b>", sub_kb())
        await cb.answer("✅ Верификация пройдена!"); return

    await cb.answer("✅ Пройдена!")
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        main_menu_text(cb.from_user.first_name, user),
        main_menu_kb(is_admin=(uid == ADMIN_ID)))

# ─── MAIN MENU CALLBACK ─────────────────────────────────────────────────────
@dp.callback_query(F.data == "main_menu")
async def main_menu_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = str(cb.from_user.id)
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")

    if user.get("banned"): await cb.answer("🚫 Бан!", show_alert=True); return

    # В ЛС — проверяем подписку
    if cb.message.chat.type == "private" and not await check_sub(uid):
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            "📢 <b>Подпишись на канал!</b>", sub_kb())
        await cb.answer(); return

    save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        main_menu_text(cb.from_user.first_name, user),
        main_menu_kb(is_admin=(uid == ADMIN_ID)))
    await cb.answer()

# ─── CATEGORY CALLBACKS ─────────────────────────────────────────────────────
@dp.callback_query(F.data == "cat_games")
async def cat_games_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or ""); save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🎮 <b>ИГРЫ</b>\n\n💰 <code>{fmt(user['balance'])}</code>\n\n"
        f"⚽ Футбол x2 | 🏀 Баскетбол x2 | 🎯 Дартс\n"
        f"💣 Мины | 📈 Краш | 🃏 21 Очко\n"
        f"🎰 Слоты | 🏆 Золото\n"
        f"⚔️ Дуэль — /duel @user ставка", games_kb())
    await cb.answer()

@dp.callback_query(F.data == "game_duel_info")
async def game_duel_info_cb(cb: CallbackQuery):
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        "⚔️ <b>Дуэль — Крестики-нолики</b>\n\n"
        "Играй против реального игрока!\n\n"
        "<b>/duel @username ставка</b>\n<b>/duel ID ставка</b>\n\n"
        "<i>Пример: /duel @player 1000000</i>\n\nПриз: x2!",
        kb([btn("🔙  Игры", "cat_games", style="primary", icon=EI_STAR)]))
    await cb.answer()

@dp.callback_query(F.data == "cat_bonus")
async def cat_bonus_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or ""); save_db(db)
    bs = "✅ Получен" if user["last_bonus"] == str(date.today()) else f"{ae('🎁', EI_OK)} Доступен"
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🎁 <b>БОНУСЫ</b>\n\n💰 <code>{fmt(user['balance'])}</code>\n\n"
        f"🎁 $1.000.000/день — {bs}\n👥 Друзей: <b>{len(user['referrals'])}</b> — $5.000.000/друг", bonus_kb())
    await cb.answer()

@dp.callback_query(F.data == "cat_info")
async def cat_info_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or ""); save_db(db)
    s = user["stats"]
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"📊 <b>ИНФОРМАЦИЯ</b>\n\n👤 <b>{safe(cb.from_user.first_name)}</b>\n"
        f"📅 С: <b>{user['joined']}</b>\n\n💰 <code>{fmt(user['balance'])}</code>\n"
        f"🎮 <b>{sum(s.values())}</b> | 🏆 <b>{s['wins']}</b> | 💀 <b>{s['losses']}</b>", info_kb())
    await cb.answer()

@dp.callback_query(F.data == "cat_rating")
async def cat_rating_cb(cb: CallbackQuery):
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        "🏆 <b>РЕЙТИНГ</b>\n\n💰 Баланс | 🏆 Победы | 💀 Поражения", rating_kb())
    await cb.answer()

@dp.callback_query(F.data == "cat_promo")
async def cat_promo_cb(cb: CallbackQuery):
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        "🎟️ <b>ПРОМОКОДЫ</b>\n\n🎟️ Ввести — админский\n👤 Пользовательский — от игроков\n"
        "➕ Создать свой (+$500.000 автору/активация)\n📋 Мой — статистика и вывод", promo_kb())
    await cb.answer()

@dp.callback_query(F.data == "cat_shop")
async def cat_shop_cb(cb: CallbackQuery):
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🛒 <b>МАГАЗИН</b>\n\n"
        f"Курс: <b>1 ⭐ = {fmt(SHOP_RATE_PER_STAR)}</b>\n\n"
        f"Выбери пакет:", shop_kb())
    await cb.answer()

@dp.callback_query(F.data.startswith("shop_buy_"))
async def shop_buy_cb(cb: CallbackQuery):
    stars = int(cb.data.split("_")[2])
    if stars not in SHOP_STAR_PACKS:
        await cb.answer("Неверный пакет!", show_alert=True); return
    await cb.answer()
    r = await send_stars_invoice(cb.message.chat.id, stars)
    if not r.get("ok"):
        await send_msg(cb.message.chat.id,
            "❌ Не удалось создать счёт. Проверь, что бот поддерживает Telegram Stars и обновлён Bot API.", back_kb())

@dp.callback_query(F.data == "cat_businesses")
async def cat_businesses_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        businesses_text(uid), businesses_kb(uid))
    await cb.answer()

@dp.callback_query(F.data.startswith("biz_buy_sale_"))
@dp.callback_query(F.data.startswith("biz_buy_"))
async def business_buy_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id)
    is_sale = cb.data.startswith("biz_buy_sale_")
    key = cb.data[len("biz_buy_sale_"):] if is_sale else cb.data[len("biz_buy_"):]
    if key not in BUSINESSES:
        await cb.answer("Бизнес не найден!", show_alert=True); return
    data = load_businesses(); rec = data[key]; cfg = BUSINESSES[key]
    owned_key = user_business_key(data, uid)
    if owned_key:
        await cb.answer(f"❌ У тебя уже есть бизнес: {BUSINESSES[owned_key]['name']}", show_alert=True); return

    if not is_sale and key == "casino":
        if rec.get("owner_id"):
            await cb.answer("Казино уже куплено!", show_alert=True); return
        await cb.answer()
        r = await send_business_stars_invoice(cb.message.chat.id, key)
        if not r.get("ok"):
            await send_msg(cb.message.chat.id, "❌ Не удалось создать счёт Stars.", back_kb())
        return

    if is_sale:
        price = int(rec.get("sale_price") or 0)
        seller_id = rec.get("owner_id")
        if not price or not seller_id:
            await cb.answer("Бизнес уже не продаётся!", show_alert=True); return
        if seller_id == uid:
            await cb.answer("Нельзя купить свой бизнес!", show_alert=True); return
    else:
        if rec.get("owner_id"):
            await cb.answer("Бизнес уже куплен!", show_alert=True); return
        price = int(cfg.get("price", 0)); seller_id = None

    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    if user["balance"] < price:
        await cb.answer("Недостаточно средств!", show_alert=True); return
    user["balance"] -= price
    if seller_id and seller_id in db:
        db[seller_id]["balance"] += price
        add_log(db, seller_id, "business_sale", f"+{fmt(price)} ({cfg['name']})")
    add_log(db, uid, "business_buy", f"-{fmt(price)} ({cfg['name']})")
    rec["owner_id"] = uid
    rec["owner_name"] = cb.from_user.first_name or "Игрок"
    rec["last_claim"] = int(time.time())
    rec["balance"] = 0
    rec["sale_price"] = None
    save_db(db); save_businesses(data)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"✅ <b>Бизнес куплен!</b>\n\n🏢 <b>{cfg['name']}</b>\n💰 Цена: <code>{fmt(price)}</code>",
        businesses_kb(uid))
    await cb.answer("✅ Куплено!")

_biz_claim_locks = set()

@dp.callback_query(F.data.startswith("biz_claim_"))
async def business_claim_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); key = cb.data[len("biz_claim_"):]
    if key not in BUSINESSES:
        await cb.answer("Бизнес не найден!", show_alert=True); return
    # FIX: защита от дюпа дохода при двойном клике
    lock_key = f"{uid}:{key}"
    if lock_key in _biz_claim_locks:
        await cb.answer("⏳ Подожди...", show_alert=True); return
    _biz_claim_locks.add(lock_key)
    try:
        data = load_businesses(); rec = data[key]
        if rec.get("owner_id") != uid:
            await cb.answer("Это не твой бизнес!", show_alert=True); return
        pending, hours = business_pending_income(key, rec)
        if pending <= 0:
            await cb.answer("Дохода пока нет!", show_alert=True); return
        db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
        user["balance"] += pending
        add_log(db, uid, "business_claim", f"+{fmt(pending)} ({BUSINESSES[key]['name']})")
        rec["balance"] = 0
        rec["last_claim"] = int(time.time())
        save_db(db); save_businesses(data)
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"✅ <b>Доход забран!</b>\n\n🏢 <b>{BUSINESSES[key]['name']}</b>\n💰 +<code>{fmt(pending)}</code>\n\nБаланс: <code>{fmt(user['balance'])}</code>",
            businesses_kb(uid))
        await cb.answer("✅ Зачислено!")
    finally:
        _biz_claim_locks.discard(lock_key)

@dp.callback_query(F.data.startswith("biz_sell_state_"))
async def business_sell_state_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id)
    key = cb.data[len("biz_sell_state_"):]
    if key not in BUSINESSES:
        await cb.answer("Бизнес не найден!", show_alert=True); return
    data = load_businesses(); rec = data[key]
    if rec.get("owner_id") != uid:
        await cb.answer("Это не твой бизнес!", show_alert=True); return

    payout = business_state_sell_price(key)
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    user["balance"] += payout
    add_log(db, uid, "business_sell_state", f"+{fmt(payout)} ({BUSINESSES[key]['name']})")

    data[key] = {"owner_id": None, "owner_name": "", "last_claim": int(time.time()), "balance": 0, "sale_price": None}
    save_db(db); save_businesses(data)

    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🏛 <b>Бизнес продан государству!</b>\n\n"
        f"🏢 <b>{BUSINESSES[key]['name']}</b>\n"
        f"💰 Получено: <code>{fmt(payout)}</code>\n\n"
        f"Баланс: <code>{fmt(user['balance'])}</code>", businesses_kb(uid))
    await cb.answer("✅ Продано в госс")

@dp.callback_query(F.data.startswith("biz_sell_select_"))
async def business_sell_select_cb(cb: CallbackQuery, state: FSMContext):
    uid = str(cb.from_user.id); key = cb.data[len("biz_sell_select_"):]
    data = load_businesses()
    if key not in BUSINESSES or data[key].get("owner_id") != uid:
        await cb.answer("Это не твой бизнес!", show_alert=True); return
    if data[key].get("sale_price"):
        await cb.answer("❌ Бизнес уже на продаже. Сначала сними его.", show_alert=True); return
    await state.set_state(BusinessStates.waiting_sell_price)
    await state.update_data(biz_key=key)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🏷 <b>Продажа бизнеса</b>\n\n"
        f"Бизнес: <b>{BUSINESSES[key]['name']}</b>\n\n"
        f"Введи цену продажи:", cancel_kb())
    await cb.answer()

# FIX: снятие бизнеса с продажи
@dp.callback_query(F.data.startswith("biz_sell_cancel_"))
async def business_sell_cancel_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); key = cb.data[len("biz_sell_cancel_"):]
    if key not in BUSINESSES:
        await cb.answer("Бизнес не найден!", show_alert=True); return
    data = load_businesses(); rec = data[key]
    if rec.get("owner_id") != uid:
        await cb.answer("Это не твой бизнес!", show_alert=True); return
    if not rec.get("sale_price"):
        await cb.answer("Этот бизнес и так не на продаже.", show_alert=True); return
    rec["sale_price"] = None
    save_businesses(data)
    db = load_db()
    add_log(db, uid, "business_sell_cancel", BUSINESSES[key]["name"])
    save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"❎ <b>Бизнес снят с продажи</b>\n\n🏢 <b>{BUSINESSES[key]['name']}</b>",
        businesses_kb(uid))
    await cb.answer("✅ Снят с продажи")

@dp.pre_checkout_query()
async def pre_checkout_cb(pre: PreCheckoutQuery):
    await tg("answerPreCheckoutQuery", pre_checkout_query_id=pre.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment_msg(msg: Message):
    sp = msg.successful_payment
    if not sp or sp.currency != "XTR":
        return
    payload = str(sp.invoice_payload)
    uid = str(msg.from_user.id)

    if payload.startswith("shop_stars_"):
        stars = int(sp.total_amount)
        amount = stars * SHOP_RATE_PER_STAR
        db = load_db(); user = get_user(db, uid, msg.from_user.first_name, msg.from_user.username or "")
        user["balance"] += amount
        add_log(db, uid, "shop_stars", f"+{fmt(amount)} за {stars}⭐")
        save_db(db)
        if uid != ADMIN_ID:
            try:
                await send_msg(int(ADMIN_ID),
                    f"🛒 <b>Покупка в магазине</b>\n\n"
                    f"👤 {safe(msg.from_user.first_name)} (<code>{uid}</code>)\n"
                    f"⭐ {stars}\n💰 {fmt(amount)}")
            except: pass
        await send_msg(msg.chat.id,
            f"✅ <b>Покупка успешна!</b>\n\n"
            f"⭐ Оплачено: <b>{stars}</b>\n"
            f"💰 Зачислено: <code>{fmt(amount)}</code>\n\n"
            f"Баланс: <code>{fmt(user['balance'])}</code>", back_kb())
        return

    if payload.startswith("biz_buy_"):
        key = payload[len("biz_buy_"):]
        if key not in BUSINESSES:
            return
        data = load_businesses(); rec = data[key]
        owned_key = user_business_key(data, uid)
        if owned_key:
            await send_msg(msg.chat.id,
                f"❌ У тебя уже есть бизнес: <b>{BUSINESSES[owned_key]['name']}</b>. Напиши админу для возврата Stars.", back_kb())
            return
        if rec.get("owner_id"):
            await send_msg(msg.chat.id, "❌ Этот бизнес уже куплен. Напиши админу для возврата Stars.", back_kb())
            return
        rec["owner_id"] = uid
        rec["owner_name"] = msg.from_user.first_name or "Игрок"
        rec["last_claim"] = int(time.time())
        rec["balance"] = 0
        rec["sale_price"] = None
        save_businesses(data)
        try:
            await send_msg(int(ADMIN_ID),
                f"🏢 <b>Куплен бизнес за Stars</b>\n\n"
                f"👤 {safe(msg.from_user.first_name)} (<code>{uid}</code>)\n"
                f"🏢 {BUSINESSES[key]['name']}\n⭐ {sp.total_amount}")
        except: pass
        await send_msg(msg.chat.id,
            f"✅ <b>Бизнес куплен!</b>\n\n🏢 <b>{BUSINESSES[key]['name']}</b>", back_kb())
        return

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
        me = " ◀️" if u_id == uid else ""
        lines.append(f"{m} <b>{safe(name)}</b> — {vf}{me}")
    pos = next((i+1 for i, (u_id, *_) in enumerate(users) if u_id == uid), None)
    if pos: lines.append(f"\n📍 Ты: <b>{pos}</b>/<b>{len(users)}</b>")
    return "\n".join(lines)

def rating_back_kb():
    return kb([btn("🔙  Рейтинг", "cat_rating", style="primary", icon=EI_STAR),
               btn("🏠  Меню", "main_menu", icon=EI_STAR)])

@dp.callback_query(F.data == "rating_balance")
async def rating_bal_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    get_user(db, uid, cb.from_user.first_name, cb.from_user.username or ""); save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        build_lb(db, uid, "balance", "По балансу", "💰"), rating_back_kb())
    await cb.answer()

@dp.callback_query(F.data == "rating_wins")
async def rating_wins_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    get_user(db, uid, cb.from_user.first_name, cb.from_user.username or ""); save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        build_lb(db, uid, "wins", "По победам", "🏆"), rating_back_kb())
    await cb.answer()

@dp.callback_query(F.data == "rating_losses")
async def rating_losses_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    get_user(db, uid, cb.from_user.first_name, cb.from_user.username or ""); save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        build_lb(db, uid, "losses", "По поражениям", "💀"), rating_back_kb())
    await cb.answer()

# ─── BALANCE / STATS / BONUS / REFERRAL ─────────────────────────────────────
@dp.callback_query(F.data == "balance")
async def balance_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or ""); save_db(db)
    s = user["stats"]
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"💰 <b>БАЛАНС</b>\n\n{ae('💵', EI_OK)} <code>{fmt(user['balance'])}</code>\n\n"
        f"🏆 <b>{s['wins']}</b> | 💀 <b>{s['losses']}</b> | 🤝 <b>{s['draws']}</b>", back_kb())
    await cb.answer()

@dp.callback_query(F.data == "stats")
async def stats_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or ""); save_db(db)
    s = user["stats"]; total = sum(s.values())
    if total == 0: rank = "🥉 Новичок"
    elif s["wins"]/total >= 0.7: rank = f"{ae('👑', EI_OK)} Легенда"
    elif s["wins"]/total >= 0.55: rank = f"{ae('💎', EI_LIKE)} Мастер"
    elif s["wins"]/total >= 0.45: rank = f"{ae('⭐', EI_STAR)} Опытный"
    else: rank = "🥉 Новичок"
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"📊 <b>СТАТИСТИКА</b>\n\n{rank}\n\n"
        f"🎮 <b>{total}</b>\n🏆 <b>{s['wins']}</b>\n💀 <b>{s['losses']}</b>\n🤝 <b>{s['draws']}</b>\n\n"
        f"💰 <code>{fmt(user['balance'])}</code>", back_kb())
    await cb.answer()

_bonus_locks = set()

@dp.callback_query(F.data == "daily_bonus")
async def daily_bonus_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id)
    # FIX: защита от двойного клика
    if uid in _bonus_locks:
        await cb.answer("⏳ Подожди...", show_alert=True); return
    _bonus_locks.add(uid)
    try:
        db = load_db()
        user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
        today = str(date.today())
        if user["last_bonus"] == today:
            await edit_msg(cb.message.chat.id, cb.message.message_id,
                f"🎁 <b>Бонус</b>\n\n⏰ Уже получен!\nЗавтра — <b>$1.000.000</b>\n\n💰 <code>{fmt(user['balance'])}</code>", back_kb())
        else:
            user["balance"] += 1_000_000; user["last_bonus"] = today
            add_log(db, uid, "bonus", "+$1.000.000"); save_db(db)
            await edit_msg(cb.message.chat.id, cb.message.message_id,
                f"🎁 <b>Бонус!</b>\n\n{ae('🎉', EI_OK)} <b>+$1.000.000</b>\n\n💰 <code>{fmt(user['balance'])}</code>", back_kb())
        await cb.answer()
    finally:
        _bonus_locks.discard(uid)

@dp.callback_query(F.data == "referral")
async def referral_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or ""); save_db(db)
    me = await bot.get_me(); link = f"https://t.me/{me.username}?start=ref_{uid}"
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"👥 <b>Рефералы</b>\n\n💰 <b>+$5.000.000</b>/друг\n👥 <b>{len(user['referrals'])}</b>\n\n🔗 <code>{link}</code>", back_kb())
    await cb.answer()

# ─── TEXT COMMAND ALIASES ───────────────────────────────────────────────────
@dp.message(F.text.lower() == "бонус")
async def bonus_text_cmd(msg: Message):
    db = load_db(); uid = str(msg.from_user.id)
    user = get_user(db, uid, msg.from_user.first_name, msg.from_user.username or "")
    today = str(date.today())
    if user["last_bonus"] == today:
        await send_msg(msg.chat.id,
            f"🎁 <b>Бонус</b>\n\n⏰ Уже получен!\nЗавтра — <b>$1.000.000</b>\n\n💰 <code>{fmt(user['balance'])}</code>", back_kb())
    else:
        user["balance"] += 1_000_000; user["last_bonus"] = today
        add_log(db, uid, "bonus", "+$1.000.000"); save_db(db)
        await send_msg(msg.chat.id,
            f"🎁 <b>Бонус!</b>\n\n{ae('🎉', EI_OK)} <b>+$1.000.000</b>\n\n💰 <code>{fmt(user['balance'])}</code>", back_kb())

@dp.message(F.text.lower() == "реф")
async def ref_text_cmd(msg: Message):
    db = load_db(); uid = str(msg.from_user.id)
    user = get_user(db, uid, msg.from_user.first_name, msg.from_user.username or ""); save_db(db)
    me = await bot.get_me(); link = f"https://t.me/{me.username}?start=ref_{uid}"
    await send_msg(msg.chat.id,
        f"👥 <b>Рефералы</b>\n\n💰 <b>+$5.000.000</b>/друг\n👥 <b>{len(user['referrals'])}</b>\n\n🔗 <code>{link}</code>", back_kb())

@dp.message(F.text.lower() == "промо")
async def promo_text_cmd(msg: Message):
    await send_msg(msg.chat.id,
        "🎟️ <b>ПРОМОКОДЫ</b>\n\n🎟️ Ввести — админский\n👤 Пользовательский — от игроков\n"
        "➕ Создать свой (+$500.000 автору/активация)\n📋 Мой — статистика и вывод", promo_kb())

@dp.message(F.text.lower() == "топ")
async def top_text_cmd(msg: Message):
    await send_msg(msg.chat.id, "🏆 <b>РЕЙТИНГ</b>\n\n💰 Баланс | 🏆 Победы | 💀 Поражения", rating_kb())

@dp.message(F.text.lower().startswith("передать"))
async def pay_text_alias_cmd(msg: Message):
    db = load_db(); uid = str(msg.from_user.id)
    user = get_user(db, uid, msg.from_user.first_name, msg.from_user.username or "")
    if not user.get("verified"):
        await send_msg(msg.chat.id, "❌ /start"); return
    if user.get("banned"):
        await send_msg(msg.chat.id, "🚫 Бан!"); return
    save_db(db)
    parts = msg.text.split()
    if len(parts) >= 3:
        amount = parse_amount(parts[1]); tid = parts[2]
        if not amount: await send_msg(msg.chat.id, "❌ Неверная сумма!"); return
        if not tid.isdigit(): await send_msg(msg.chat.id, "❌ ID — число!"); return
        db = load_db(); ok, text_pay = await do_pay(msg, db, uid, tid, amount)
        if ok: save_db(db)
        await send_msg(msg.chat.id, text_pay); return
    if len(parts) == 2 and msg.reply_to_message:
        amount = parse_amount(parts[1])
        if not amount: await send_msg(msg.chat.id, "❌ Неверная сумма!"); return
        tid = str(msg.reply_to_message.from_user.id)
        db = load_db(); ok, text_pay = await do_pay(msg, db, uid, tid, amount)
        if ok: save_db(db)
        await send_msg(msg.chat.id, text_pay); return
    await send_msg(msg.chat.id,
        "💸 <b>Передать</b>\n\nФормат:\n<code>передать сумма ID</code>\nили ответом на сообщение: <code>передать сумма</code>")

@dp.message(Command("sellbiz"))
async def sellbiz_cmd(msg: Message):
    uid = str(msg.from_user.id)
    data = load_businesses()
    owned = [key for key in BUSINESSES if data[key].get("owner_id") == uid]
    if not owned:
        await send_msg(msg.chat.id, "❌ У тебя нет бизнеса для продажи.", back_kb()); return
    await send_msg(msg.chat.id, "🏷 <b>Выбери бизнес для продажи:</b>", sellbiz_choose_kb(uid))

@dp.message(BusinessStates.waiting_sell_price)
async def sellbiz_price_msg(msg: Message, state: FSMContext):
    amount = parse_amount(msg.text.strip())
    if not amount:
        await send_msg(msg.chat.id, "❌ Неверная цена!", cancel_kb()); return
    data_state = await state.get_data(); key = data_state.get("biz_key")
    uid = str(msg.from_user.id)
    data = load_businesses()
    if key not in BUSINESSES or data[key].get("owner_id") != uid:
        await state.clear(); await send_msg(msg.chat.id, "❌ Это уже не твой бизнес.", back_kb()); return
    data[key]["sale_price"] = amount
    save_businesses(data); await state.clear()
    await send_msg(msg.chat.id,
        f"✅ <b>Бизнес выставлен на продажу!</b>\n\n"
        f"🏢 <b>{BUSINESSES[key]['name']}</b>\n"
        f"🏷 Цена: <code>{fmt(amount)}</code>", back_kb())

# ═══════════════════════════════════════════════════════════════════════════════
# ПРОМОКОДЫ
# ═══════════════════════════════════════════════════════════════════════════════
@dp.callback_query(F.data == "promo_enter")
async def promo_enter_cb(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PromoStates.enter_admin_code)
    await edit_msg(cb.message.chat.id, cb.message.message_id, "🎟️ <b>Ввести промокод</b>\n\nВведи код:", cancel_kb())
    await cb.answer()

@dp.message(PromoStates.enter_admin_code)
async def promo_admin_code(msg: Message, state: FSMContext):
    code = msg.text.strip().upper(); db = load_db(); promos = load_promos()
    uid = str(msg.from_user.id); user = get_user(db, uid, msg.from_user.first_name, msg.from_user.username or "")
    if code not in promos.get("admin", {}):
        await send_msg(msg.chat.id, "❌ Не найден! Ещё раз:", cancel_kb()); return
    promo = promos["admin"][code]
    limit = int(promo.get("limit", 0) or 0)
    used = int(promo.get("used", 0) or 0)
    if limit and used >= limit:
        await state.clear(); await send_msg(msg.chat.id, "❌ У промокода закончились активации!", back_promo_kb()); return
    activated = db[uid].get("activated_promos", [])
    if code in activated:
        await state.clear(); await send_msg(msg.chat.id, "❌ Уже активирован!", back_promo_kb()); return
    amount = promo["amount"]; user["balance"] += amount
    promo["used"] = used + 1
    db[uid].setdefault("activated_promos", []).append(code)
    add_log(db, uid, "promo", f"+{fmt(amount)} ({code})")
    save_db(db); save_promos(promos); await state.clear()
    await send_msg(msg.chat.id,
        f"✅ <b>Активирован!</b>\n\n🎟️ <code>{code}</code>\n💰 +<code>{fmt(amount)}</code>\n\n💰 <code>{fmt(user['balance'])}</code>", back_promo_kb())

@dp.callback_query(F.data == "promo_user_enter")
async def promo_user_enter_cb(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PromoStates.enter_user_code)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"👤 <b>Промо пользователя</b>\n\nВведи код от игрока:\n<i>Ты: +{fmt(PROMO_USER_REWARD)} | Автор: +{fmt(PROMO_CREATOR_REWARD)} на промо-баланс</i>", cancel_kb())
    await cb.answer()

@dp.message(PromoStates.enter_user_code)
async def promo_user_code(msg: Message, state: FSMContext):
    code = msg.text.strip().upper(); db = load_db(); promos = load_promos()
    uid = str(msg.from_user.id); user = get_user(db, uid, msg.from_user.first_name, msg.from_user.username or "")
    if code not in promos.get("user", {}):
        await send_msg(msg.chat.id, "❌ Не найден!", cancel_kb()); return
    promo = promos["user"][code]; creator_id = promo["creator_id"]
    if creator_id == uid: await send_msg(msg.chat.id, "❌ Твой промокод!", cancel_kb()); return
    if uid in promo.get("activated_by", []): await send_msg(msg.chat.id, "❌ Уже использовал!", cancel_kb()); return
    user["balance"] += PROMO_USER_REWARD
    if creator_id in db:
        db[creator_id]["promo_earnings"] = db[creator_id].get("promo_earnings", 0) + PROMO_CREATOR_REWARD
        try:
            await send_msg(int(creator_id),
                f"🎟️ Твой промо активирован!\n💰 Промо-баланс: <code>{fmt(db[creator_id]['promo_earnings'])}</code>\n\n<i>Забери в «Мой промокод»</i>")
        except: pass
    promo.setdefault("activated_by", []).append(uid); promo["activations"] = len(promo["activated_by"])
    add_log(db, uid, "user_promo", f"+{fmt(PROMO_USER_REWARD)} ({code})")
    save_db(db); save_promos(promos); await state.clear()
    await send_msg(msg.chat.id,
        f"✅ <b>Активирован!</b>\n\n🎟️ <code>{code}</code>\n💰 +<code>{fmt(PROMO_USER_REWARD)}</code>\n\n💰 <code>{fmt(user['balance'])}</code>", back_promo_kb())

@dp.callback_query(F.data == "promo_create")
async def promo_create_cb(cb: CallbackQuery, state: FSMContext):
    # FIX: блокируем повторное создание промокода
    uid = str(cb.from_user.id)
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    if user.get("created_promo"):
        await cb.answer("❌ У тебя уже есть промокод!", show_alert=True)
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"❌ <b>Свой промокод можно создать только 1 раз!</b>\n\n"
            f"🎟️ Твой код: <code>{user['created_promo']}</code>\n\n"
            f"<i>Открой «📋 Мой промокод», чтобы увидеть статистику.</i>", back_promo_kb())
        return
    await state.set_state(PromoStates.create_code)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        "➕ <b>Создать промокод</b>\n\nКод (3-15, латиница+цифры):\n<i>+ $500.000 за активацию на промо-баланс</i>", cancel_kb())
    await cb.answer()

@dp.message(PromoStates.create_code)
async def promo_create_msg(msg: Message, state: FSMContext):
    code = msg.text.strip().upper(); uid = str(msg.from_user.id)
    # FIX: повторная проверка на момент сохранения (защита от гонок и обхода через FSM)
    db = load_db(); user = get_user(db, uid, msg.from_user.first_name, msg.from_user.username or "")
    if user.get("created_promo"):
        await state.clear()
        await send_msg(msg.chat.id,
            f"❌ <b>У тебя уже есть промокод!</b>\n\n🎟️ <code>{user['created_promo']}</code>", back_promo_kb())
        return
    if len(code) < 3 or len(code) > 15 or not code.isalnum():
        await send_msg(msg.chat.id, "❌ 3-15, латиница+цифры!", cancel_kb()); return
    promos = load_promos()
    if code in promos.get("admin", {}) or code in promos.get("user", {}):
        await send_msg(msg.chat.id, "❌ Занят!", cancel_kb()); return
    # FIX: дополнительно — один промо на одного автора в promos.json
    for c, p in promos.get("user", {}).items():
        if str(p.get("creator_id")) == uid:
            db[uid]["created_promo"] = c; save_db(db); await state.clear()
            await send_msg(msg.chat.id,
                f"❌ <b>У тебя уже есть промокод!</b>\n\n🎟️ <code>{c}</code>", back_promo_kb())
            return
    promos.setdefault("user", {})[code] = {"creator_id": uid, "activations": 0, "activated_by": []}
    db[uid]["created_promo"] = code; save_db(db); save_promos(promos); await state.clear()
    await send_msg(msg.chat.id,
        f"✅ <b>Создан!</b>\n\n🎟️ <code>{code}</code>\n💰 Автору: +{fmt(PROMO_CREATOR_REWARD)} за активацию\n👤 Игроку: +{fmt(PROMO_USER_REWARD)}\n\n<i>Поделись!</i>", back_promo_kb())

@dp.callback_query(F.data == "promo_my")
async def promo_my_cb(cb: CallbackQuery):
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or ""); save_db(db)
    code = user.get("created_promo"); pe = user.get("promo_earnings", 0)
    if not code:
        await edit_msg(cb.message.chat.id, cb.message.message_id, "📋 <b>Мой промокод</b>\n\nПока нет. Создай выше!", back_promo_kb())
        await cb.answer(); return
    promos = load_promos(); p = promos.get("user", {}).get(code, {}); acts = p.get("activations", 0)
    rows = []
    if pe > 0: rows.append([btn(f"💰 Забрать {fmt(pe)}", "promo_withdraw", style="success", icon=EI_OK)])
    rows.append([btn("🔙  Промокоды", "cat_promo", style="primary", icon=EI_STAR)])
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"📋 <b>Мой промокод</b>\n\n🎟️ <code>{code}</code>\n👥 Активаций: <b>{acts}</b>\n\n"
        f"💰 Промо-баланс: <code>{fmt(pe)}</code>\n<i>Заработано: {fmt(acts * PROMO_CREATOR_REWARD)}</i>", {"inline_keyboard": rows})
    await cb.answer()

_withdraw_locks = set()

@dp.callback_query(F.data == "promo_withdraw")
async def promo_withdraw_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id)
    # FIX: защита от дюпа при быстром двойном клике
    if uid in _withdraw_locks:
        await cb.answer("⏳ Подожди...", show_alert=True); return
    _withdraw_locks.add(uid)
    try:
        db = load_db()
        user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
        pe = user.get("promo_earnings", 0)
        if pe <= 0:
            await cb.answer("Нечего забирать!", show_alert=True); return
        user["balance"] += pe; add_log(db, uid, "promo_withdraw", f"+{fmt(pe)}")
        user["promo_earnings"] = 0; save_db(db)
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"✅ <b>Забрано!</b>\n\n+<code>{fmt(pe)}</code>\n\n💰 Баланс: <code>{fmt(user['balance'])}</code>", back_promo_kb())
        await cb.answer("✅ Зачислено!")
    finally:
        _withdraw_locks.discard(uid)

# ═══════════════════════════════════════════════════════════════════════════════
# АДМИН-ПАНЕЛЬ
# ═══════════════════════════════════════════════════════════════════════════════
def admin_only(cb): return str(cb.from_user.id) == ADMIN_ID

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_cb(cb: CallbackQuery):
    if not admin_only(cb): await cb.answer("❌", show_alert=True); return
    db = load_db(); total = sum(1 for u in db.values() if u.get("verified"))
    bal = sum(u.get("balance", 0) for u in db.values())
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🛠️ <b>АДМИН</b>\n\n👥 <b>{total}</b>\n💰 <code>{fmt(bal)}</code>", admin_kb())
    await cb.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.broadcast)
    await edit_msg(cb.message.chat.id, cb.message.message_id, "📢 <b>Рассылка</b>\n\nТекст:", cancel_kb()); await cb.answer()

@dp.message(AdminStates.broadcast)
async def admin_broadcast_msg(msg: Message, state: FSMContext):
    if str(msg.from_user.id) != ADMIN_ID: await state.clear(); return
    db = load_db(); sent = fail = 0
    for u_id, u in db.items():
        if not u.get("verified"): continue
        try: await send_msg(int(u_id), msg.text); sent += 1
        except: fail += 1
    await state.clear()
    await send_msg(msg.chat.id, f"✅ <b>Рассылка</b>\n\n📬 {sent} | ❌ {fail}", admin_kb())

@dp.callback_query(F.data == "admin_ban_unban")
async def admin_ban_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.target_id); await state.update_data(action="ban")
    await edit_msg(cb.message.chat.id, cb.message.message_id, "🔨 <b>Бан/Разбан</b>\n\nID:", cancel_kb()); await cb.answer()

@dp.callback_query(F.data == "admin_check_balance")
async def admin_checkbal_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.target_id); await state.update_data(action="balance")
    await edit_msg(cb.message.chat.id, cb.message.message_id, "💰 <b>Баланс игрока</b>\n\nID:", cancel_kb()); await cb.answer()

@dp.callback_query(F.data == "admin_logs")
async def admin_logs_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.target_id); await state.update_data(action="logs")
    await edit_msg(cb.message.chat.id, cb.message.message_id, "📋 <b>Логи</b>\n\nID:", cancel_kb()); await cb.answer()

@dp.callback_query(F.data == "admin_give")
async def admin_give_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.target_id); await state.update_data(action="give")
    await edit_msg(cb.message.chat.id, cb.message.message_id, "💸 <b>Выдать $</b>\n\nID:", cancel_kb()); await cb.answer()

@dp.callback_query(F.data == "admin_take")
async def admin_take_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.target_id); await state.update_data(action="take")
    await edit_msg(cb.message.chat.id, cb.message.message_id, "📥 <b>Забрать $</b>\n\nID:", cancel_kb()); await cb.answer()

@dp.callback_query(F.data == "admin_give_business")
async def admin_give_business_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.target_id); await state.update_data(action="give_business")
    await edit_msg(cb.message.chat.id, cb.message.message_id, "🏢 <b>Выдать бизнес</b>\n\nID игрока:", cancel_kb()); await cb.answer()

@dp.callback_query(F.data == "admin_take_business")
async def admin_take_business_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.target_id); await state.update_data(action="take_business")
    await edit_msg(cb.message.chat.id, cb.message.message_id, "📥 <b>Забрать бизнес</b>\n\nID игрока:", cancel_kb()); await cb.answer()

@dp.callback_query(F.data.startswith("admin_biz_"))
async def admin_business_action_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    parts = cb.data.split("_")
    action = parts[2] + "_" + parts[3]
    target_id = parts[4]
    key = "_".join(parts[5:])
    if key not in BUSINESSES:
        await cb.answer("Бизнес не найден!", show_alert=True); return
    data = load_businesses(); db = load_db()
    if target_id not in db:
        await cb.answer("Игрок не найден!", show_alert=True); return
    if action == "give_business":
        if user_has_business(data, target_id):
            owned = user_business_key(data, target_id)
            await cb.answer(f"У игрока уже есть бизнес: {BUSINESSES[owned]['name']}", show_alert=True); return
        if data[key].get("owner_id"):
            await cb.answer("Этот бизнес уже занят!", show_alert=True); return
        data[key]["owner_id"] = target_id
        data[key]["owner_name"] = db[target_id].get("name", "Игрок")
        data[key]["last_claim"] = int(time.time())
        data[key]["balance"] = 0
        data[key]["sale_price"] = None
        add_log(db, target_id, "admin_give_business", BUSINESSES[key]["name"])
        text_done = f"✅ <b>Бизнес выдан!</b>\n\n👤 <code>{target_id}</code>\n🏢 <b>{BUSINESSES[key]['name']}</b>"
    else:
        if data[key].get("owner_id") != target_id:
            await cb.answer("У игрока нет этого бизнеса!", show_alert=True); return
        data[key] = {"owner_id": None, "owner_name": "", "last_claim": int(time.time()), "balance": 0, "sale_price": None}
        add_log(db, target_id, "admin_take_business", BUSINESSES[key]["name"])
        text_done = f"✅ <b>Бизнес забран!</b>\n\n👤 <code>{target_id}</code>\n🏢 <b>{BUSINESSES[key]['name']}</b>"
    save_businesses(data); save_db(db); await state.clear()
    await edit_msg(cb.message.chat.id, cb.message.message_id, text_done, admin_kb())
    await cb.answer("✅ Готово")

@dp.callback_query(F.data == "admin_reset")
async def admin_reset_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.target_id); await state.update_data(action="reset")
    await edit_msg(cb.message.chat.id, cb.message.message_id, "🗑️ <b>Обнулить</b>\n\nID:", cancel_kb()); await cb.answer()

@dp.callback_query(F.data == "admin_create_promo")
async def admin_promo_cb(cb: CallbackQuery, state: FSMContext):
    if not admin_only(cb): return
    await state.set_state(AdminStates.promo_code)
    await edit_msg(cb.message.chat.id, cb.message.message_id, "🎟️ <b>Создать промо</b>\n\nКод:", cancel_kb()); await cb.answer()

@dp.message(AdminStates.target_id)
async def admin_target_id(msg: Message, state: FSMContext):
    if str(msg.from_user.id) != ADMIN_ID: await state.clear(); return
    tid = msg.text.strip()
    if not tid.isdigit(): await send_msg(msg.chat.id, "❌ ID — число!", cancel_kb()); return
    data = await state.get_data(); action = data["action"]; db = load_db()
    if tid not in db: await send_msg(msg.chat.id, "❌ Не найден!", cancel_kb()); return
    tname = db[tid].get("name", "—")

    if action == "ban":
        banned = db[tid].get("banned", False); db[tid]["banned"] = not banned
        add_log(db, tid, "ban" if not banned else "unban", "admin"); save_db(db); await state.clear()
        st = "🔒 ЗАБАНЕН" if not banned else "✅ РАЗБАНЕН"
        await send_msg(msg.chat.id, f"✅ <b>{st}</b>\n\n👤 <b>{safe(tname)}</b> (<code>{tid}</code>)", admin_kb())
    elif action == "balance":
        s = db[tid].get("stats", {"wins":0,"losses":0,"draws":0}); await state.clear()
        await send_msg(msg.chat.id,
            f"💰 <b>{safe(tname)}</b> (<code>{tid}</code>)\n\n💰 <code>{fmt(db[tid]['balance'])}</code>\n🏆 {s['wins']} | 💀 {s['losses']} | 🤝 {s['draws']}", admin_kb())
    elif action == "logs":
        logs = db[tid].get("user_logs", []); lines = [f"📋 <b>{safe(tname)}</b> (<code>{tid}</code>)\n"]
        if not logs: lines.append("Пусто.")
        else:
            for l in logs[:20]: lines.append(f"[{l.get('time','')}] {l.get('action','')} — {l.get('detail','')}")
        await state.clear(); await send_msg(msg.chat.id, "\n".join(lines), admin_kb())
    elif action in ("give", "take"):
        await state.update_data(target_id=tid); await state.set_state(AdminStates.amount)
        w = "Выдать" if action == "give" else "Забрать"
        await send_msg(msg.chat.id, f"{'💸' if action=='give' else '📥'} <b>{w}</b>\n\n👤 <b>{safe(tname)}</b> — <code>{fmt(db[tid]['balance'])}</code>\n\nСумма:", cancel_kb())
    elif action in ("give_business", "take_business"):
        await state.clear()
        title = "Выдать бизнес" if action == "give_business" else "Забрать бизнес"
        kb_biz = admin_business_choose_kb(action, tid)
        if len(kb_biz["inline_keyboard"]) <= 1:
            await send_msg(msg.chat.id, f"❌ Нет доступных бизнесов для действия: <b>{title}</b>", admin_kb()); return
        await send_msg(msg.chat.id, f"🏢 <b>{title}</b>\n\n👤 <b>{safe(tname)}</b> (<code>{tid}</code>)\n\nВыбери бизнес:", kb_biz)
    elif action == "reset":
        db[tid]["balance"] = 0; db[tid]["promo_earnings"] = 0
        db[tid]["stats"] = {"wins": 0, "losses": 0, "draws": 0}
        db[tid]["activated_promos"] = []; db[tid]["user_logs"] = []
        add_log(db, tid, "reset", "обнулён"); save_db(db); await state.clear()
        await send_msg(msg.chat.id,
            f"🗑️ <b>Обнулён!</b>\n\n👤 <b>{safe(tname)}</b> (<code>{tid}</code>)\n💰 $0 | 📊 Сброшено", admin_kb())

@dp.message(AdminStates.amount)
async def admin_amount_msg(msg: Message, state: FSMContext):
    if str(msg.from_user.id) != ADMIN_ID: await state.clear(); return
    amount = parse_amount(msg.text.strip())
    if not amount: await send_msg(msg.chat.id, "❌ Неверная сумма!", cancel_kb()); return
    data = await state.get_data(); action = data["action"]; tid = data["target_id"]
    db = load_db(); tname = db.get(tid, {}).get("name", "—")
    if action == "give":
        if tid in db: db[tid]["balance"] = db[tid].get("balance", 0) + amount
        add_log(db, tid, "admin_give", f"+{fmt(amount)}"); w = "Выдано"
    else:
        if tid in db: db[tid]["balance"] = max(0, db[tid].get("balance", 0) - amount)
        add_log(db, tid, "admin_take", f"-{fmt(amount)}"); w = "Списано"
    save_db(db); await state.clear()
    bal = db.get(tid, {}).get("balance", 0)
    await send_msg(msg.chat.id, f"✅ <b>{w}: {fmt(amount)}</b>\n\n👤 <b>{safe(tname)}</b>\n💰 <code>{fmt(bal)}</code>", admin_kb())

@dp.message(AdminStates.promo_code)
async def admin_promo_code_msg(msg: Message, state: FSMContext):
    if str(msg.from_user.id) != ADMIN_ID: await state.clear(); return
    code = msg.text.strip().upper()
    if len(code) < 3 or len(code) > 15 or not code.isalnum():
        await send_msg(msg.chat.id, "❌ 3-15, латиница+цифры!", cancel_kb()); return
    promos = load_promos()
    if code in promos.get("admin", {}) or code in promos.get("user", {}):
        await send_msg(msg.chat.id, "❌ Занят!", cancel_kb()); return
    await state.update_data(promo_code=code); await state.set_state(AdminStates.promo_amount)
    await send_msg(msg.chat.id, f"🎟️ <code>{code}</code>\n\nСумма награды:", cancel_kb())

@dp.message(AdminStates.promo_amount)
async def admin_promo_amount_msg(msg: Message, state: FSMContext):
    if str(msg.from_user.id) != ADMIN_ID: await state.clear(); return
    amount = parse_amount(msg.text.strip())
    if not amount: await send_msg(msg.chat.id, "❌ Неверная сумма!", cancel_kb()); return
    await state.update_data(promo_amount=amount)
    await state.set_state(AdminStates.promo_activations)
    await send_msg(msg.chat.id,
        f"🎟️ <b>Промокод</b>\n\n💰 Награда: <code>{fmt(amount)}</code>\n\nКоличество активаций:", cancel_kb())

@dp.message(AdminStates.promo_activations)
async def admin_promo_activations_msg(msg: Message, state: FSMContext):
    if str(msg.from_user.id) != ADMIN_ID: await state.clear(); return
    limit = parse_amount(msg.text.strip())
    if not limit: await send_msg(msg.chat.id, "❌ Неверное количество!", cancel_kb()); return
    data = await state.get_data(); code = data["promo_code"]; amount = data["promo_amount"]
    promos = load_promos()
    promos.setdefault("admin", {})[code] = {"amount": amount, "limit": limit, "used": 0, "created": str(date.today())}
    save_promos(promos); await state.clear()
    await send_msg(msg.chat.id,
        f"✅ <b>Создан!</b>\n\n🎟️ <code>{code}</code>\n💰 <code>{fmt(amount)}</code>\n👥 Активаций: <b>{limit}</b>", admin_kb())

# ═══════════════════════════════════════════════════════════════════════════════
# ИГРЫ
# ═══════════════════════════════════════════════════════════════════════════════
GAME_INFO = {
    "football":   ("⚽ Футбол",    "Ударь по воротам!\nx2 🥅"),
    "mines":      ("💣 Мины",      "Выбери количество мин и открывай 💎"),
    "basketball": ("🏀 Баскетбол", "Бросок в кольцо!\nx2 🏀"),
    "slots":      ("🎰 Слоты",     "2 одинаковых — x1.5\n3 одинаковых — x5"),
    "darts":      ("🎯 Дартс",     "Попади ближе к центру — множитель выше"),
    "crash":      ("📈 Краш",      "Выбери множитель и успей до краша"),
    "blackjack":  ("🃏 21 Очко",   "Набери ближе к 21, чем дилер"),
    "gold":       ("🏆 Золото",    "12 уровней — найди золото"),
}

@dp.callback_query(F.data.startswith("game_"))
async def game_menu_cb(cb: CallbackQuery):
    game = cb.data[5:]
    if game == "duel_info": await game_duel_info_cb(cb); return
    name, desc = GAME_INFO[game]
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"<b>{name}</b>\n\n{desc}\n\n💵 Ставка:", bet_kb(game)); await cb.answer()

@dp.callback_query(F.data.startswith("bet_"))
async def bet_cb(cb: CallbackQuery):
    _, game, bet_str = cb.data.split("_", 2); bet = int(bet_str)
    db = load_db(); uid = str(cb.from_user.id)
    user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    if user.get("banned"): await cb.answer("🚫 Бан!", show_alert=True); return
    save_db(db)
    if user["balance"] < bet:
        await cb.answer()
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"❌ Мало средств!\n\n<code>{fmt(user['balance'])}</code> | Ставка: <code>{fmt(bet)}</code>", back_kb()); return
    if uid in duel_player_map: await cb.answer("❌ Закончи дуэль!", show_alert=True); return
    if uid in sessions and sessions[uid].get("game") == "mines":
        await cb.answer("❌ Сначала закончи мины или забери выигрыш!", show_alert=True); return
    sessions.pop(uid, None)  # очищаем старую незавершённую подготовку футбола/баскетбола/выбора мин
    await cb.answer()
    if game == "football":     await start_football(cb, db, uid, bet)
    elif game == "mines":      await show_mines_count_menu(cb, uid, bet)
    elif game == "basketball": await start_basketball(cb, db, uid, bet)
    elif game == "slots":      await start_slots(cb, db, uid, bet)
    elif game == "darts":      await start_darts(cb, db, uid, bet)
    elif game == "crash":      await start_crash(cb, db, uid, bet)
    elif game == "blackjack":  await start_blackjack(cb, db, uid, bet)
    elif game == "gold":       await start_gold(cb, db, uid, bet)

@dp.callback_query(F.data.startswith("custom_bet_"))
async def custom_bet_cb(cb: CallbackQuery, state: FSMContext):
    game = cb.data.split("_", 2)[2]
    if game not in GAME_INFO:
        await cb.answer("Игра не найдена!", show_alert=True); return
    await state.set_state(BetStates.waiting_amount)
    await state.update_data(game=game)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"✍️ <b>Своя ставка</b>\n\n"
        f"Игра: <b>{GAME_INFO[game][0]}</b>\n"
        f"Максимум: <code>{fmt(CUSTOM_BET_MAX)}</code>\n\n"
        f"Введи сумму:", cancel_kb())
    await cb.answer()

@dp.message(BetStates.waiting_amount)
async def custom_bet_amount_msg(msg: Message, state: FSMContext):
    amount = parse_amount(msg.text.strip())
    if not amount:
        await send_msg(msg.chat.id, "❌ Неверная сумма!", cancel_kb()); return
    if amount > CUSTOM_BET_MAX:
        await send_msg(msg.chat.id, f"❌ Максимальная ставка: <code>{fmt(CUSTOM_BET_MAX)}</code>", cancel_kb()); return

    data = await state.get_data(); game = data.get("game")
    await state.clear()
    db = load_db(); uid = str(msg.from_user.id)
    user = get_user(db, uid, msg.from_user.first_name, msg.from_user.username or "")
    if user.get("banned"):
        await send_msg(msg.chat.id, "🚫 Бан!"); return
    if uid in duel_player_map:
        await send_msg(msg.chat.id, "❌ Закончи дуэль!"); return
    if uid in sessions and sessions[uid].get("game") == "mines":
        await send_msg(msg.chat.id, "❌ Сначала закончи мины или забери выигрыш!"); return
    if user["balance"] < amount:
        await send_msg(msg.chat.id, f"❌ Мало средств!\n\nБаланс: <code>{fmt(user['balance'])}</code>\nСтавка: <code>{fmt(amount)}</code>", back_kb()); return
    save_db(db)

    r = await send_msg(msg.chat.id, "✅ Ставка принята, запускаю игру...")
    bot_msg_id = r.get("result", {}).get("message_id", msg.message_id)
    fake_cb = type("FakeCb", (), {})()
    fake_msg = type("FakeMsg", (), {})()
    fake_msg.chat = msg.chat
    fake_msg.message_id = bot_msg_id
    fake_cb.message = fake_msg
    fake_cb.from_user = msg.from_user

    if game == "football":     await start_football(fake_cb, db, uid, amount)
    elif game == "mines":      await show_mines_count_menu(fake_cb, uid, amount)
    elif game == "basketball": await start_basketball(fake_cb, db, uid, amount)
    elif game == "slots":      await start_slots(fake_cb, db, uid, amount)
    elif game == "darts":      await start_darts(fake_cb, db, uid, amount)
    elif game == "crash":      await start_crash(fake_cb, db, uid, amount)
    elif game == "blackjack":  await start_blackjack(fake_cb, db, uid, amount)
    elif game == "gold":       await start_gold(fake_cb, db, uid, amount)


# ⚽ ФУТБОЛ
def football_kb():
    return kb([btn("⚽ Ударить", "football_kick", style="success", icon=EI_OK)])

async def start_football(cb, db, uid, bet):
    sessions[uid] = {"game":"football","bet":bet}
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"{ae('⚽',EI_OK)} <b>Пенальти!</b>\n\n"
        f"Ставка: <code>{fmt(bet)}</code>\n"
        f"Выигрыш: <code>{fmt(bet * 2)}</code>\n\n"
        f"Нажми, чтобы ударить.", football_kb())

@dp.callback_query(F.data == "football_kick")
async def football_shot_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id)
    sess = sessions.pop(uid, None)
    if not sess or sess.get("game") != "football": await cb.answer("Новая игра!", show_alert=True); return
    await cb.answer("⚽ Удар!"); bet = sess["bet"]; payout = bet * 2
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    if user["balance"] < bet:
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"❌ Мало средств!\n\nБаланс: <code>{fmt(user['balance'])}</code>\nСтавка: <code>{fmt(bet)}</code>", back_kb()); return

    user["balance"] -= bet
    add_log(db, uid, "football_bet", f"ставка {fmt(bet)}")
    save_db(db)

    await edit_msg(cb.message.chat.id, cb.message.message_id, f"{ae('⚽',EI_OK)} <b>Удар...</b>")
    dice = await send_dice(cb.message.chat.id, "⚽")
    value = get_dice_value(dice)
    if not value:
        value = random.randint(1, 5)
    await asyncio.sleep(4.0)

    # Для футбола Telegram Bot API возвращает value 1..5.
    # 3, 4, 5 — гол; 1, 2 — промах/штанга.
    win = value in (3, 4, 5)
    if win:
        user["balance"] += payout; user["stats"]["wins"] += 1
        r = f"{ae('🎉',EI_OK)} <b>ГОЛ!</b> +<code>{fmt(payout)}</code>"; add_log(db, uid, "football_win", f"+{fmt(payout - bet)} | payout={fmt(payout)} | dice={value}")
    else:
        user["stats"]["losses"] += 1
        r = f"{ae('🥅',EI_WARN)} <b>Мимо!</b> -<code>{fmt(bet)}</code>"; add_log(db, uid, "football_loss", f"-{fmt(bet)} | dice={value}")
        add_business_loss_income(bet)
    save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"⚽ <b>Результат</b>\n\n{r}\n\n💰 <code>{fmt(user['balance'])}</code>", game_nav_kb("game_football"))

# 🏀 БАСКЕТБОЛ
def basketball_kb():
    return kb([btn("🏀 Бросить", "bball_throw", style="success", icon=EI_OK)])

async def start_basketball(cb, db, uid, bet):
    sessions[uid] = {"game":"basketball","bet":bet}
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"{ae('🏀',EI_OK)} <b>Штрафной!</b>\n\n"
        f"Ставка: <code>{fmt(bet)}</code>\n"
        f"Выигрыш: <code>{fmt(bet * 2)}</code>\n\n"
        f"Нажми, чтобы бросить.", basketball_kb())

@dp.callback_query(F.data == "bball_throw")
async def bball_shot_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id)
    sess = sessions.pop(uid, None)
    if not sess or sess.get("game") != "basketball": await cb.answer("Новая игра!", show_alert=True); return
    await cb.answer("🏀 Бросок!"); bet = sess["bet"]; payout = bet * 2
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    if user["balance"] < bet:
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"❌ Мало средств!\n\nБаланс: <code>{fmt(user['balance'])}</code>\nСтавка: <code>{fmt(bet)}</code>", back_kb()); return

    user["balance"] -= bet
    add_log(db, uid, "basketball_bet", f"ставка {fmt(bet)}")
    save_db(db)

    await edit_msg(cb.message.chat.id, cb.message.message_id, f"{ae('🏀',EI_OK)} <b>Бросок...</b>")
    dice = await send_dice(cb.message.chat.id, "🏀")
    value = get_dice_value(dice)
    if not value:
        value = random.randint(1, 5)
    await asyncio.sleep(4.0)

    # Для баскетбола Telegram Bot API возвращает value 1..5.
    # 4 и 5 — попадание; 1..3 — промах.
    win = value in (4, 5)
    if win:
        user["balance"] += payout; user["stats"]["wins"] += 1
        r = f"{ae('🎉',EI_OK)} <b>Попал!</b> +<code>{fmt(payout)}</code>"; add_log(db, uid, "basketball_win", f"+{fmt(payout - bet)} | payout={fmt(payout)} | dice={value}")
    else:
        user["stats"]["losses"] += 1
        r = f"{ae('🚫',EI_WARN)} <b>Промах!</b> -<code>{fmt(bet)}</code>"; add_log(db, uid, "basketball_loss", f"-{fmt(bet)} | dice={value}")
        add_business_loss_income(bet)
    save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🏀 <b>Результат</b>\n\n{r}\n\n💰 <code>{fmt(user['balance'])}</code>", game_nav_kb("game_basketball"))

# 🎰 СЛОТЫ
def slots_kb():
    return kb([btn("🎰 Крутить", "slots_spin", style="success", icon=EI_OK)])

def slot_symbols(value):
    v = max(0, int(value) - 1)
    return [v % 4, (v // 4) % 4, (v // 16) % 4]

async def start_slots(cb, db, uid, bet):
    sessions[uid] = {"game":"slots","bet":bet}
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"{ae('🎰',EI_WARN)} <b>Слоты</b>\n\n"
        f"Ставка: <code>{fmt(bet)}</code>\n\n"
        f"2 одинаковых — <b>x1.5</b>\n"
        f"3 одинаковых — <b>x5</b>", slots_kb())

@dp.callback_query(F.data == "slots_spin")
async def slots_spin_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id)
    sess = sessions.pop(uid, None)
    if not sess or sess.get("game") != "slots": await cb.answer("Новая игра!", show_alert=True); return
    await cb.answer("🎰 Крутим!"); bet = sess["bet"]
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    if user["balance"] < bet:
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"❌ Мало средств!\n\nБаланс: <code>{fmt(user['balance'])}</code>\nСтавка: <code>{fmt(bet)}</code>", back_kb()); return

    user["balance"] -= bet
    add_log(db, uid, "slots_bet", f"ставка {fmt(bet)}")
    save_db(db)

    await edit_msg(cb.message.chat.id, cb.message.message_id, f"{ae('🎰',EI_WARN)} <b>Крутим...</b>")
    dice = await send_dice(cb.message.chat.id, "🎰")
    value = get_dice_value(dice)
    if not value:
        value = random.randint(1, 64)
    await asyncio.sleep(4.0)

    symbols = slot_symbols(value)
    max_same = max(symbols.count(s) for s in set(symbols))
    if max_same == 3:
        mult = 5.0
    elif max_same == 2:
        mult = 1.5
    else:
        mult = 0

    if mult > 0:
        payout = int(bet * mult)
        user["balance"] += payout; user["stats"]["wins"] += 1
        r = f"🎰 <b>{max_same} одинаковых!</b> x{mult:g}\n+<code>{fmt(payout)}</code>"
        add_log(db, uid, "slots_win", f"payout={fmt(payout)} | x{mult:g} | dice={value}")
    else:
        user["stats"]["losses"] += 1
        r = f"💀 <b>Не совпало</b>\n-<code>{fmt(bet)}</code>"
        add_log(db, uid, "slots_loss", f"-{fmt(bet)} | dice={value}")
        add_business_loss_income(bet)
    save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🎰 <b>Результат</b>\n\n{r}\n\n💰 <code>{fmt(user['balance'])}</code>", game_nav_kb("game_slots"))

# 🎯 ДАРТС
def darts_kb():
    return kb([btn("🎯 Бросить", "darts_throw", style="success", icon=EI_OK)])

async def start_darts(cb, db, uid, bet):
    sessions[uid] = {"game":"darts","bet":bet}
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🎯 <b>Дартс</b>\n\n"
        f"Ставка: <code>{fmt(bet)}</code>\n\n"
        f"3 — x1.2 | 4 — x1.5 | 5 — x2 | 6 — x3", darts_kb())

@dp.callback_query(F.data == "darts_throw")
async def darts_throw_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id)
    sess = sessions.pop(uid, None)
    if not sess or sess.get("game") != "darts": await cb.answer("Новая игра!", show_alert=True); return
    await cb.answer("🎯 Бросок!"); bet = sess["bet"]
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    if user["balance"] < bet:
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"❌ Мало средств!\n\nБаланс: <code>{fmt(user['balance'])}</code>\nСтавка: <code>{fmt(bet)}</code>", back_kb()); return
    user["balance"] -= bet; add_log(db, uid, "darts_bet", f"ставка {fmt(bet)}"); save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id, "🎯 <b>Бросок...</b>")
    dice = await send_dice(cb.message.chat.id, "🎯")
    value = get_dice_value(dice) or random.randint(1, 6)
    await asyncio.sleep(4.0)
    mults = {3: 1.2, 4: 1.5, 5: 2.0, 6: 3.0}
    mult = mults.get(value, 0)
    if mult:
        payout = int(bet * mult)
        user["balance"] += payout; user["stats"]["wins"] += 1
        r = f"🎯 <b>Попадание!</b> x{mult:g}\n+<code>{fmt(payout)}</code>"
        add_log(db, uid, "darts_win", f"payout={fmt(payout)} | x{mult:g} | dice={value}")
    else:
        user["stats"]["losses"] += 1
        r = f"💀 <b>Мимо</b>\n-<code>{fmt(bet)}</code>"
        add_log(db, uid, "darts_loss", f"-{fmt(bet)} | dice={value}")
        add_business_loss_income(bet)
    save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🎯 <b>Результат</b>\n\n{r}\n\n💰 <code>{fmt(user['balance'])}</code>", game_nav_kb("game_darts"))

# 📈 КРАШ
CRASH_TARGETS = [1.2, 1.5, 2.0, 3.0, 5.0]

def crash_kb():
    rows = []
    for i in range(0, len(CRASH_TARGETS), 2):
        rows.append([btn(f"x{m:g}", f"crash_target_{str(m).replace('.', '_')}", style="success", icon=EI_OK) for m in CRASH_TARGETS[i:i+2]])
    return {"inline_keyboard": rows}

async def start_crash(cb, db, uid, bet):
    sessions[uid] = {"game":"crash","bet":bet}
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"📈 <b>Краш</b>\n\nСтавка: <code>{fmt(bet)}</code>\n\nВыбери множитель для выхода:", crash_kb())

def random_crash_point():
    r = random.random()
    if r < 0.45: return round(random.uniform(1.00, 1.49), 2)
    if r < 0.75: return round(random.uniform(1.50, 2.49), 2)
    if r < 0.92: return round(random.uniform(2.50, 4.99), 2)
    return round(random.uniform(5.00, 10.00), 2)

@dp.callback_query(F.data.startswith("crash_target_"))
async def crash_target_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id)
    sess = sessions.pop(uid, None)
    if not sess or sess.get("game") != "crash": await cb.answer("Новая игра!", show_alert=True); return
    target = float(cb.data[len("crash_target_"):].replace("_", ".")); bet = sess["bet"]
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    if user["balance"] < bet:
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"❌ Мало средств!\n\nБаланс: <code>{fmt(user['balance'])}</code>\nСтавка: <code>{fmt(bet)}</code>", back_kb()); return
    user["balance"] -= bet; add_log(db, uid, "crash_bet", f"ставка {fmt(bet)} | цель x{target:g}"); save_db(db)
    await cb.answer("📈 Запуск!")
    crash_at = random_crash_point()
    await edit_msg(cb.message.chat.id, cb.message.message_id, f"📈 <b>Растёт...</b>\n\nЦель: <b>x{target:g}</b>")
    await asyncio.sleep(2.0)
    if crash_at >= target:
        payout = int(bet * target)
        user["balance"] += payout; user["stats"]["wins"] += 1
        r = f"✅ <b>Успел!</b> x{target:g}\n+<code>{fmt(payout)}</code>\n\nКраш был на x{crash_at:g}"
        add_log(db, uid, "crash_win", f"payout={fmt(payout)} | target=x{target:g} | crash=x{crash_at:g}")
    else:
        user["stats"]["losses"] += 1
        r = f"💥 <b>Краш на x{crash_at:g}</b>\n-<code>{fmt(bet)}</code>"
        add_log(db, uid, "crash_loss", f"-{fmt(bet)} | target=x{target:g} | crash=x{crash_at:g}")
        add_business_loss_income(bet)
    save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"📈 <b>Краш</b>\n\n{r}\n\n💰 <code>{fmt(user['balance'])}</code>", game_nav_kb("game_crash"))

# 🃏 21 ОЧКО
CARD_DECK = [(str(n), n) for n in range(2, 11)] + [("В", 2), ("Д", 3), ("К", 4), ("Т", 11)]

def bj_draw(): return random.choice(CARD_DECK)
def bj_total(cards):
    total = sum(v for _, v in cards)
    aces = sum(1 for n, _ in cards if n == "Т")
    while total > 21 and aces:
        total -= 10; aces -= 1
    return total

def bj_cards_text(cards): return " ".join(n for n, _ in cards)
def blackjack_kb():
    return kb([btn("➕ Ещё", "bj_hit", style="success", icon=EI_OK), btn("✋ Стоп", "bj_stand", style="primary", icon=EI_STAR)])

def blackjack_finish_kb(): return game_nav_kb("game_blackjack")

async def start_blackjack(cb, db, uid, bet):
    player = [bj_draw(), bj_draw()]
    dealer = [bj_draw(), bj_draw()]
    sessions[uid] = {"game":"blackjack","bet":bet,"player":player,"dealer":dealer,"charged":False}
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🃏 <b>21 Очко</b>\n\nСтавка: <code>{fmt(bet)}</code>\n\n"
        f"Твои карты: <b>{bj_cards_text(player)}</b> = <b>{bj_total(player)}</b>\n"
        f"Карта дилера: <b>{dealer[0][0]}</b>\n\n"
        f"Победа — x2, 21 с раздачи — x2.5", blackjack_kb())

async def bj_charge_if_needed(uid, cb, sess):
    bet = sess["bet"]
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    if sess.get("charged"):
        return True, db, user
    if user["balance"] < bet:
        return False, db, user
    user["balance"] -= bet; sess["charged"] = True
    add_log(db, uid, "blackjack_bet", f"ставка {fmt(bet)}"); save_db(db)
    return True, db, user

@dp.callback_query(F.data == "bj_hit")
async def bj_hit_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); sess = sessions.get(uid)
    if not sess or sess.get("game") != "blackjack": await cb.answer("Новая игра!", show_alert=True); return
    ok, db, user = await bj_charge_if_needed(uid, cb, sess)
    if not ok:
        sessions.pop(uid, None); await edit_msg(cb.message.chat.id, cb.message.message_id, "❌ Мало средств!", back_kb()); return
    sess["player"].append(bj_draw())
    total = bj_total(sess["player"]); bet = sess["bet"]
    if total > 21:
        sessions.pop(uid, None); user["stats"]["losses"] += 1
        add_log(db, uid, "blackjack_loss", f"-{fmt(bet)} | bust"); add_business_loss_income(bet); save_db(db)
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"🃏 <b>Перебор!</b>\n\nТвои карты: <b>{bj_cards_text(sess['player'])}</b> = <b>{total}</b>\n\n-<code>{fmt(bet)}</code>\n\n💰 <code>{fmt(user['balance'])}</code>", blackjack_finish_kb())
        await cb.answer(); return
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🃏 <b>21 Очко</b>\n\nТвои карты: <b>{bj_cards_text(sess['player'])}</b> = <b>{total}</b>\nКарта дилера: <b>{sess['dealer'][0][0]}</b>", blackjack_kb())
    await cb.answer()

@dp.callback_query(F.data == "bj_stand")
async def bj_stand_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); sess = sessions.pop(uid, None)
    if not sess or sess.get("game") != "blackjack": await cb.answer("Новая игра!", show_alert=True); return
    ok, db, user = await bj_charge_if_needed(uid, cb, sess)
    if not ok:
        await edit_msg(cb.message.chat.id, cb.message.message_id, "❌ Мало средств!", back_kb()); return
    bet = sess["bet"]; player = sess["player"]; dealer = sess["dealer"]
    while bj_total(dealer) < 17:
        dealer.append(bj_draw())
    pt, dt = bj_total(player), bj_total(dealer)
    blackjack = (len(player) == 2 and pt == 21)
    if dt > 21 or pt > dt:
        mult = 2.5 if blackjack else 2.0
        payout = int(bet * mult); user["balance"] += payout; user["stats"]["wins"] += 1
        r = f"🏆 <b>Победа!</b> x{mult:g}\n+<code>{fmt(payout)}</code>"
        add_log(db, uid, "blackjack_win", f"payout={fmt(payout)} | x{mult:g}")
    elif pt == dt:
        user["balance"] += bet; user["stats"].setdefault("draws", 0); user["stats"]["draws"] += 1
        r = f"🤝 <b>Ничья</b>\nСтавка возвращена: <code>{fmt(bet)}</code>"
        add_log(db, uid, "blackjack_draw", "ставка вернулась")
    else:
        user["stats"]["losses"] += 1
        r = f"💀 <b>Проигрыш</b>\n-<code>{fmt(bet)}</code>"
        add_log(db, uid, "blackjack_loss", f"-{fmt(bet)}"); add_business_loss_income(bet)
    save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🃏 <b>21 Очко</b>\n\n"
        f"Ты: <b>{bj_cards_text(player)}</b> = <b>{pt}</b>\n"
        f"Дилер: <b>{bj_cards_text(dealer)}</b> = <b>{dt}</b>\n\n"
        f"{r}\n\n💰 <code>{fmt(user['balance'])}</code>", blackjack_finish_kb())
    await cb.answer()

# 🏆 ЗОЛОТО
GOLD_MULTS = [1.15, 1.30, 1.50, 1.75, 2.05, 2.40, 2.85, 3.35, 4.00, 4.80, 5.80, 7.00]

def gold_kb(level, can_cashout=True):
    rows = [[btn("⬛", f"gold_pick_{i}", style="primary", icon=EI_STAR) for i in range(3)]]
    if can_cashout and level > 0:
        rows.append([btn(f"✅ Забрать x{GOLD_MULTS[level-1]:.2f}", "gold_cashout", style="success", icon=EI_OK)])
    return {"inline_keyboard": rows}

async def start_gold(cb, db, uid, bet):
    sessions[uid] = {"game":"gold","bet":bet,"level":0,"charged":False}
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🏆 <b>Золото</b>\n\nСтавка: <code>{fmt(bet)}</code>\n"
        f"12 уровней. На каждом уровне выбери ячейку с золотом.\n"
        f"Уровень 1: множитель <b>x{GOLD_MULTS[0]:.2f}</b>", gold_kb(0, False))

async def gold_charge_if_needed(uid, cb, sess):
    bet = sess["bet"]; db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    if sess.get("charged"):
        return True, db, user
    if user["balance"] < bet: return False, db, user
    user["balance"] -= bet; sess["charged"] = True
    add_log(db, uid, "gold_bet", f"ставка {fmt(bet)}"); save_db(db)
    return True, db, user

@dp.callback_query(F.data.startswith("gold_pick_"))
async def gold_pick_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); sess = sessions.get(uid)
    if not sess or sess.get("game") != "gold": await cb.answer("Новая игра!", show_alert=True); return
    ok, db, user = await gold_charge_if_needed(uid, cb, sess)
    if not ok:
        sessions.pop(uid, None); await edit_msg(cb.message.chat.id, cb.message.message_id, "❌ Мало средств!", back_kb()); return
    pick = int(cb.data.split("_")[2]); gold = random.randint(0, 2)
    bet = sess["bet"]; level = sess["level"]
    if pick != gold:
        sessions.pop(uid, None); user["stats"]["losses"] += 1
        add_log(db, uid, "gold_loss", f"-{fmt(bet)} | level={level+1}"); add_business_loss_income(bet); save_db(db)
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"🏆 <b>Золото</b>\n\nПусто! Золото было в ячейке <b>{gold+1}</b>.\n\n-<code>{fmt(bet)}</code>\n\n💰 <code>{fmt(user['balance'])}</code>", game_nav_kb("game_gold"))
        await cb.answer(); return
    level += 1; sess["level"] = level
    mult = GOLD_MULTS[level-1]; payout = int(bet * mult)
    if level >= len(GOLD_MULTS):
        sessions.pop(uid, None); user["balance"] += payout; user["stats"]["wins"] += 1
        add_log(db, uid, "gold_win", f"payout={fmt(payout)} | x{mult:.2f}"); save_db(db)
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"🏆 <b>Все 12 уровней пройдены!</b>\n\nВыплата: <code>{fmt(payout)}</code> (x{mult:.2f})\n\n💰 <code>{fmt(user['balance'])}</code>", game_nav_kb("game_gold"))
        await cb.answer(); return
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"🏆 <b>Золото найдено!</b>\n\n"
        f"Уровень: <b>{level}</b>/12\n"
        f"Можно забрать: <code>{fmt(payout)}</code> (x{mult:.2f})\n"
        f"Следующий уровень: x{GOLD_MULTS[level]:.2f}", gold_kb(level, True))
    await cb.answer("✅ Золото!")

@dp.callback_query(F.data == "gold_cashout")
async def gold_cashout_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); sess = sessions.pop(uid, None)
    if not sess or sess.get("game") != "gold": await cb.answer("Нет игры!", show_alert=True); return
    level = sess.get("level", 0)
    if level <= 0:
        await cb.answer("Сначала найди золото!", show_alert=True); return
    bet = sess["bet"]; mult = GOLD_MULTS[level-1]; payout = int(bet * mult)
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    user["balance"] += payout; user["stats"]["wins"] += 1
    add_log(db, uid, "gold_cashout", f"payout={fmt(payout)} | x{mult:.2f}"); save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"✅ <b>Забрал золото!</b>\n\nУровень: <b>{level}</b>/12\nВыплата: <code>{fmt(payout)}</code> (x{mult:.2f})\n\n💰 <code>{fmt(user['balance'])}</code>", game_nav_kb("game_gold"))
    await cb.answer("💰 Забрал!")

# 💣 МИНЫ
MINES_GRID = 16
MINES_OPTIONS = [2, 3, 4, 5, 6, 8, 10, 12]
# Чем больше мин, тем быстрее растёт множитель за каждую открытую безопасную клетку.
MINES_STEPS = {2: 0.05, 3: 0.07, 4: 0.10, 5: 0.13, 6: 0.16, 8: 0.22, 10: 0.35, 12: 0.60}

def mines_count_kb(bet):
    rows = []
    for i in range(0, len(MINES_OPTIONS), 2):
        row = []
        for m in MINES_OPTIONS[i:i+2]:
            row.append(btn(f"💣 {m} мин", f"mines_count_{m}", style="danger" if m >= 8 else "primary", icon=EI_WARN))
        rows.append(row)
    rows.append([btn("🔙 Игры", "cat_games", style="primary", icon=EI_STAR)])
    return {"inline_keyboard": rows}

async def show_mines_count_menu(cb, uid, bet):
    sessions[uid] = {"game": "mines_select", "bet": bet}
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"{ae('💣',EI_WARN)} <b>Мины</b>\n\n"
        f"Ставка: <code>{fmt(bet)}</code>\n\n"
        f"Выбери количество мин. Чем больше мин — тем выше множитель.",
        mines_count_kb(bet))

def mines_safe_total(mines_count):
    return MINES_GRID - int(mines_count)

def mines_safe_opened(revealed, mines):
    return len([r for r in revealed if r not in mines])

def mines_multiplier(safe_opened, mines_count):
    safe_opened = max(0, min(mines_safe_total(mines_count), int(safe_opened)))
    if safe_opened <= 0:
        return 1.00
    step = MINES_STEPS.get(int(mines_count), 0.10)
    return round(1.0 + safe_opened * step, 2)

def mines_payout(bet, safe_opened, mines_count):
    if safe_opened <= 0:
        return 0
    return int(round(bet * mines_multiplier(safe_opened, mines_count)))

def mines_kb(revealed, mines, bet_val=0, dead=False, won=False):
    mines_count = len(mines)
    sym = {0:"⬛","safe":"💎","mine":"💥","hidden_mine":"💣"}; rows = []
    safe_opened = mines_safe_opened(revealed, mines)
    for rs in range(0, MINES_GRID, 4):
        row = []
        for i in range(rs, rs+4):
            if i in revealed:
                s = "mine" if i in mines else "safe"; row.append({"text": sym[s], "callback_data": "noop"})
            elif dead and i in mines:
                row.append({"text": sym["hidden_mine"], "callback_data": "noop"})
            else:
                cd = "noop" if (dead or won) else f"mines_open_{i}"; row.append({"text": sym[0], "callback_data": cd})
        rows.append(row)
    if dead or won:
        rows.append([btn("🔄 Ещё","game_mines",style="success",icon=EI_OK), btn("🎮 Игры","cat_games",style="primary",icon=EI_LIKE)])
        rows.append([btn("🏠 Меню","main_menu",icon=EI_STAR)])
    else:
        if safe_opened <= 0:
            rows.append([btn("✅ Забрать: открой клетку", "noop", style="primary", icon=EI_STAR)])
        else:
            payout = mines_payout(bet_val, safe_opened, mines_count)
            rows.append([btn(f"✅ Забрать {fmt(payout)} (x{mines_multiplier(safe_opened, mines_count):.2f})", "mines_cashout", style="success", icon=EI_OK)])
    return {"inline_keyboard": rows}

@dp.callback_query(F.data.startswith("mines_count_"))
async def mines_count_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id)
    mines_count = int(cb.data.split("_")[2])
    if mines_count not in MINES_OPTIONS:
        await cb.answer("Неверное количество мин!", show_alert=True); return
    sess = sessions.pop(uid, None)
    if not sess or sess.get("game") != "mines_select":
        await cb.answer("Выбери ставку заново!", show_alert=True); return
    bet = sess["bet"]
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    if user["balance"] < bet:
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"❌ Мало средств!\n\nБаланс: <code>{fmt(user['balance'])}</code>\nСтавка: <code>{fmt(bet)}</code>", back_kb()); return
    await cb.answer()
    await start_mines(cb, db, uid, bet, mines_count)

async def start_mines(cb, db, uid, bet, mines_count):
    user = db[uid]
    user["balance"] -= bet
    add_log(db, uid, "mines_bet", f"ставка {fmt(bet)} | мин={mines_count}")
    save_db(db)

    mines = set(random.sample(range(MINES_GRID), mines_count))
    sessions[uid] = {"game":"mines","bet":bet,"mines":list(mines),"revealed":[],"mines_count":mines_count}
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"{ae('💣',EI_WARN)} <b>Мины</b>\n\n"
        f"Ставка: <code>{fmt(bet)}</code> списана | Мин: <b>{mines_count}</b>/<b>{MINES_GRID}</b>\n"
        f"💰 Баланс: <code>{fmt(user['balance'])}</code>\n\n"
        f"Открывай безопасные клетки 💎 и забирай выигрыш.",
        mines_kb([], mines, bet))

@dp.callback_query(F.data.startswith("mines_open_"))
async def mines_open_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); idx = int(cb.data.split("_")[2])
    sess = sessions.get(uid)
    if not sess or sess["game"] != "mines": await cb.answer("Новая игра!", show_alert=True); return
    await cb.answer()
    mines = set(sess["mines"]); revealed = sess["revealed"]; bet = sess["bet"]; mines_count = sess.get("mines_count", len(mines))
    if idx in revealed:
        await cb.answer("Уже открыто!", show_alert=True); return

    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    if idx in mines:
        revealed.append(idx); user["stats"]["losses"] += 1
        add_log(db, uid, "mines_loss", f"-{fmt(bet)} | мин={mines_count}"); add_business_loss_income(bet); save_db(db); sessions.pop(uid, None)
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"{ae('💥',EI_WARN)} <b>БУМ!</b>\n\n"
            f"Ставка сгорела: -<code>{fmt(bet)}</code>\n\n"
            f"💰 <code>{fmt(user['balance'])}</code>", mines_kb(revealed, mines, bet, dead=True)); return
    revealed.append(idx)
    safe_opened = mines_safe_opened(revealed, mines); safe_total = mines_safe_total(mines_count); safe_left = safe_total - safe_opened
    mult = mines_multiplier(safe_opened, mines_count); payout = mines_payout(bet, safe_opened, mines_count)
    if safe_left == 0:
        user["balance"] += payout; user["stats"]["wins"] += 1
        add_log(db, uid, "mines_win", f"payout={fmt(payout)} | x{mult:.2f} | мин={mines_count}"); add_business_win_income(payout); save_db(db); sessions.pop(uid, None)
        await edit_msg(cb.message.chat.id, cb.message.message_id,
            f"{ae('🏆',EI_OK)} <b>Все безопасные клетки открыты!</b>\n\n"
            f"Множитель: <b>x{mult:.2f}</b>\n"
            f"Выплата: <code>{fmt(payout)}</code>\n\n"
            f"💰 <code>{fmt(user['balance'])}</code>", mines_kb(revealed, mines, bet, won=True)); return
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"💣 <b>Мины</b>\n\n"
        f"💣 Мин: <b>{mines_count}</b> | 💎 {safe_opened}/{safe_total}\n"
        f"📈 Множитель: <b>x{mult:.2f}</b>\n"
        f"💰 Забрать: <code>{fmt(payout)}</code>", mines_kb(revealed, mines, bet))

@dp.callback_query(F.data == "mines_cashout")
async def mines_cashout_cb(cb: CallbackQuery):
    uid = str(cb.from_user.id); sess = sessions.get(uid)
    if not sess or sess.get("game") != "mines": await cb.answer("Нет игры!", show_alert=True); return
    mines = set(sess["mines"]); revealed = sess["revealed"]; bet = sess["bet"]; mines_count = sess.get("mines_count", len(mines))
    safe_opened = mines_safe_opened(revealed, mines)
    if safe_opened <= 0:
        await cb.answer("Сначала открой хотя бы одну клетку!", show_alert=True); return

    sessions.pop(uid, None)
    await cb.answer("💰 Забрал!")
    mult = mines_multiplier(safe_opened, mines_count); payout = mines_payout(bet, safe_opened, mines_count)
    db = load_db(); user = get_user(db, uid, cb.from_user.first_name, cb.from_user.username or "")
    user["balance"] += payout; user["stats"]["wins"] += 1
    add_log(db, uid, "mines_cashout", f"payout={fmt(payout)} | x{mult:.2f} | мин={mines_count}"); add_business_win_income(payout); save_db(db)
    await edit_msg(cb.message.chat.id, cb.message.message_id,
        f"{ae('✅',EI_OK)} <b>Забрал!</b>\n\n"
        f"💎 Открыто: <b>{safe_opened}</b>/<b>{mines_safe_total(mines_count)}</b>\n"
        f"📈 Множитель: <b>x{mult:.2f}</b>\n"
        f"Выплата: <code>{fmt(payout)}</code>\n\n"
        f"💰 <code>{fmt(user['balance'])}</code>", game_nav_kb("game_mines"))

# ─── NOOP ────────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "noop")
async def noop_cb(cb: CallbackQuery): await cb.answer()

# ─── UNKNOWN COMMAND ─────────────────────────────────────────────────────────
@dp.message(F.text.startswith("/"))
async def unknown_cmd(msg: Message):
    await send_msg(msg.chat.id, "Упс, неизвестная команда, используй команду /help")

# ─── MAIN ────────────────────────────────────────────────────────────────────
async def main():
    print("🎮 gamGems запущен!")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
