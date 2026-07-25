import json
from datetime import datetime
from aiogram import Router, F, types, Bot
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from database import (get_user_settings, update_user_setting, add_subscription_days, 
                      register_user, is_invoice_processed, mark_invoice_processed)
from payments import create_invoice, check_invoice
from config import SUBSCRIPTION_PRICE, SUBSCRIPTION_DAYS, TRIAL_DAYS, REFERRAL_TRIAL_DAYS, REFERRER_BONUS_DAYS
from states import SettingsState

router = Router()

async def refresh(cb, text, kb):
    try:
        if cb.message.text != text or cb.message.reply_markup != kb:
            await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        else: await cb.answer()
    except: await cb.answer()

async def get_menu(user_id):
    user = await get_user_settings(user_id)
    paused = user.get('is_paused', 0) if user else 0
    btn = "▶️ СТАРТ" if paused else "⏸ СТОП"
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=btn)],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="⚙️ Настройки")],
        [KeyboardButton(text="📊 Биржи"), KeyboardButton(text="🤝 Рефералка")],
        [KeyboardButton(text="📖 Инструкция")] 
    ], resize_keyboard=True)

@router.message(CommandStart())
async def cmd_start(msg: types.Message, command: CommandObject, bot: Bot):
    uid = msg.from_user.id
    if not await get_user_settings(uid):
        ref_id, trial = 0, TRIAL_DAYS
        if command and command.args and command.args.isdigit():
            rid = int(command.args)
            if rid != uid and await get_user_settings(rid):
                ref_id, trial = rid, REFERRAL_TRIAL_DAYS
                await add_subscription_days(rid, REFERRER_BONUS_DAYS)
                try: await bot.send_message(rid, f"<b>+1 Реферал.</b> Баланс: +{REFERRER_BONUS_DAYS} дн.", parse_mode="HTML")
                except: pass
        await register_user(uid, trial, ref_id)
        txt = (f"<b>IMPULSE TERMINAL</b>\n\n"
               f"Привет. Это сканер аномалий рынка.\n\n"
               f"<b>Триал:</b> {trial} дней.\n"
               f"<b>Цена:</b> ${SUBSCRIPTION_PRICE}/мес.\n\n"
               f"Нажми <b>'📖 Инструкция'</b>, чтобы понять, как все работает.")
        await msg.answer(txt, reply_markup=await get_menu(uid), parse_mode="HTML")
    else:
        await msg.answer("Терминал готов.", reply_markup=await get_menu(uid))

@router.message(F.text == "📖 Инструкция")
async def instruction_handler(message: types.Message):
    text = (
        "<b>📖 Инструкция по Терминалу</b>\n\n"
        "Это сканнер, который ищет резкие движения цены (импульсы) и помогает понять, стоит ли в них входить.\n\n"
        "<b>1. Основные настройки:</b>\n\n"
        "• <b>Таймфрейм (ТФ):</b> Как быстро цена должна измениться (5м = за 5 минут).\n"
        "• <b>Триггер:</b> На сколько % цена должна измениться (3% = рост/падение на 3%).\n"
        "• <b>Настройки:</b> прочие параметры сигнала в зависимости от ваших требований.\n"
        "• <b>Спящий режим:</b> позволяет отключать поток сигналов на определенный промежуток времени\n\n"
        "<b>2. Информация и фильтры</b>\n\n"
        "• <b>Объем</b> — количество проторгованных контрактов за период. Показывает силу и интерес рынка.\n"
        "• <b>Открытый интерес</b> — количество открытых контрактов.\n"
        "• <b>Фандинг</b> — периодическая плата между покупателями и продавцами на фьючерсах.\n"
        "• <b>Индикатор RSI</b> — показывает перекупленность/перепроданность.\n\n"
        "• <b>Приоритет сигнала (★)</b> — Оценка от 1 до 5. Чем больше звезд, тем надежнее.\n"
        "• <b>Аномалия объема</b> — Во сколько раз объем превышает норму. x5.0 и выше — отлично.\n"
        "• <b>Фильтр BTC</b> — Блокирует сигналы против глобального тренда Биткоина."
    )
    await message.answer(text, parse_mode="HTML")

@router.message(F.text.in_({"⏸ СТОП", "▶️ СТАРТ"}))
async def pause(msg: types.Message):
    u = await get_user_settings(msg.from_user.id)
    if not u: return
    ns = not u.get('is_paused', 0)
    await update_user_setting(msg.from_user.id, 'is_paused', ns)
    await msg.answer("Остановлено." if ns else "Запущено.", reply_markup=await get_menu(msg.from_user.id))

@router.message(F.text == "👤 Профиль")
async def profile(msg: types.Message):
    await show_profile(msg)

async def show_profile(obj):
    uid = obj.from_user.id
    msg = obj.message if isinstance(obj, types.CallbackQuery) else obj
    u = await get_user_settings(uid)
    
    end = "Нет"
    days_left = 0
    try:
        dt = datetime.fromisoformat(u['subscription_end_date'])
        days_left = (dt - datetime.now()).days
        if days_left < 0: days_left = 0
        end = f"{dt.strftime('%d.%m')}"
    except: pass
    
    username = obj.from_user.first_name

    txt = (
        "Раздел: \"Профиль\"\n"
        f"User: {username}\n"
        f"ID: {uid}\n"
        f"Подписка: {end} ({days_left} дн.)"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="Продлить", callback_data="pay")
    kb.button(text="Настройки", callback_data="settings")
    
    if isinstance(obj, types.CallbackQuery): await refresh(obj, txt, kb.as_markup())
    else: await msg.answer(txt, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "pay")
async def pay(cb: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="Оплатить", callback_data="invoice")
    kb.button(text="Назад", callback_data="back_prof")
    await refresh(cb, f"<b>Оплата</b>\n${SUBSCRIPTION_PRICE} = {SUBSCRIPTION_DAYS} дней", kb.as_markup())

@router.callback_query(F.data == "back_prof")
async def back_prof(cb: types.CallbackQuery): await show_profile(cb)

@router.callback_query(F.data == "invoice")
async def invoice(cb: types.CallbackQuery):
    await cb.message.edit_text("Счет...")
    inv = await create_invoice(cb.fromuser.id if hasattr(cb, 'fromuser') else cb.from_user.id, SUBSCRIPTION_PRICE)
    if not inv: return await cb.message.edit_text("Ошибка создания счета.")
    
    kb = InlineKeyboardBuilder()
    kb.button(text="Оплатить", url=inv.bot_invoice_url)
    kb.button(text="Я оплатил", callback_data=f"chk_{inv.invoice_id}")
    kb.button(text="Отмена", callback_data="pay")
    kb.adjust(1)
    await cb.message.edit_text(f"Счет #{inv.invoice_id}", reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("chk_"))
async def check(cb: types.CallbackQuery):
    inv_id = int(cb.data.split("_")[1])
    
    if await is_invoice_processed(inv_id):
        return await cb.answer("Этот счет уже был успешно оплачен и зачислен!", show_alert=True)
        
    inv = await check_invoice(inv_id)
    if inv and inv.status == 'paid':
        await mark_invoice_processed(inv_id)
        d = await add_subscription_days(cb.from_user.id, SUBSCRIPTION_DAYS)
        await cb.message.edit_text(f"✅ Оплачено. Доступ продлен до: {d.strftime('%d.%m.%Y')}")
    else: 
        await cb.answer("Счет еще не оплачен. Проверьте статус позже.", show_alert=True)

@router.message(F.text == "⚙️ Настройки")
async def settings(msg: types.Message): await show_set(msg)
@router.callback_query(F.data == "settings")
async def settings_cb(cb: types.CallbackQuery): await show_set(cb)

async def show_set(obj):
    u = await get_user_settings(obj.from_user.id)
    sleep_status = "✅" if u['sleep_enabled'] else "❌"

    txt = (
        "<b>Конфигурация:</b>\n\n"
        f"• Таймфрейм: {u['interval']}м\n"
        f"• Триггер цены: {u['threshold']}%\n"
        f"• Спящий режим: {sleep_status}\n\n"
        "Нажмите <b>«Параметры»</b>, чтобы настроить фильтры и данные сигнала."
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=f"ТФ: {u['interval']}м", callback_data="menu_int")
    kb.button(text=f"Триггер: {u['threshold']}%", callback_data="menu_thr")
    kb.button(text="Параметры", callback_data="menu_params") 
    kb.button(text=f"Сон: {'ВКЛ' if u['sleep_enabled'] else 'ВЫКЛ'}", callback_data="menu_slp")
    kb.adjust(2)
    
    if isinstance(obj, types.CallbackQuery): await refresh(obj, txt, kb.as_markup())
    else: await obj.answer(txt, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "menu_params")
async def menu_params(cb: types.CallbackQuery):
    txt = (
        "<b>Параметры сигнала:</b>\n\n"
        "Выберите раздел для настройки:"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="Информация", callback_data="menu_p_info")
    kb.button(text="Фильтры", callback_data="menu_p_filters")
    kb.button(text="Назад", callback_data="settings")
    kb.adjust(2) 
    await refresh(cb, txt, kb.as_markup())

@router.callback_query(F.data == "menu_p_info")
async def menu_p_info(cb: types.CallbackQuery):
    u = await get_user_settings(cb.from_user.id)
    
    s_vol24 = "✅" if u.get('show_vol24') else "❌"
    s_rsi = "✅" if u.get('rsi_enabled') else "❌"
    s_vola = "✅" if u.get('show_volatility') else "❌"
    s_oi = "✅" if u.get('show_oi_change') else "❌"
    s_fund = "✅" if u.get('show_funding') else "❌"
    s_sr = "✅" if u.get('show_sr_levels') else "❌"

    txt = "<b>Раздел: Информация</b>\nВключите данные, которые хотите видеть в сигнале."
    
    kb = InlineKeyboardBuilder()
    kb.button(text=f"{s_vol24} Объем 24ч", callback_data="ti_show_vol24")
    kb.button(text=f"{s_rsi} RSI (Настр.)", callback_data="menu_rsi")
    kb.button(text=f"{s_vola} Волатильность", callback_data="ti_show_volatility")
    kb.button(text=f"{s_oi} Open Interest", callback_data="ti_show_oi_change")
    kb.button(text=f"{s_fund} Фандинг", callback_data="ti_show_funding")
    kb.button(text=f"{s_sr} Уровни S/R", callback_data="ti_show_sr_levels")
    
    kb.button(text="Назад", callback_data="menu_params")
    kb.adjust(2)
    
    await refresh(cb, txt, kb.as_markup())

@router.callback_query(F.data == "menu_p_filters")
async def menu_p_filters(cb: types.CallbackQuery):
    u = await get_user_settings(cb.from_user.id)
    
    s_prio = "✅" if u.get('show_signal_strength') else "❌"
    s_anom = "✅" if u.get('show_volume_anomaly') else "❌"
    s_btc = "✅" if u.get('filter_btc_enabled') else "❌"

    txt = "<b>Раздел: Фильтры</b>\nНастройте фильтрацию сигналов."

    kb = InlineKeyboardBuilder()
    kb.button(text=f"{s_prio} Приоритет", callback_data="tf_show_signal_strength")
    kb.button(text=f"{s_anom} Аномалия", callback_data="tf_show_volume_anomaly")
    kb.button(text=f"{s_btc} Фильтр BTC", callback_data="tf_filter_btc_enabled")
    
    kb.button(text="Назад", callback_data="menu_params")
    kb.adjust(1)
    
    await refresh(cb, txt, kb.as_markup())

@router.callback_query(F.data.startswith("ti_"))
async def toggle_info(cb: types.CallbackQuery):
    col = cb.data.split("ti_")[1]
    u = await get_user_settings(cb.from_user.id)
    await update_user_setting(cb.from_user.id, col, not u.get(col))
    await menu_p_info(cb)

@router.callback_query(F.data.startswith("tf_"))
async def toggle_filter(cb: types.CallbackQuery):
    col = cb.data.split("tf_")[1]
    u = await get_user_settings(cb.from_user.id)
    await update_user_setting(cb.from_user.id, col, not u.get(col))
    await menu_p_filters(cb)

@router.message(F.text == "📊 Биржи")
async def exch(msg: types.Message): await show_exch(msg)

async def show_exch(obj):
    u = await get_user_settings(obj.from_user.id)
    try: lst = json.loads(u['exchanges'])
    except: lst = []
    
    kb = InlineKeyboardBuilder()
    display_names = {
        "binance": "👘BINANCE", "bybit": "🎓BYBIT", "mexc": "🧩MEXC",
        "okx": "🎹OKX", "kucoin": "🥏KUCOIN", "bitget": "⚗️BITGET",
        "gate": "🐠GATEIO", "bingx": "🧊BINGX"
    }
    all_exchanges = ["binance", "bybit", "mexc", "okx", "kucoin", "bitget", "gate", "bingx"]
    for e in all_exchanges:
        s = "✅" if e in lst else "❌"
        name = display_names.get(e, e.upper())
        kb.button(text=f"{s} {name}", callback_data=f"te_{e}")
    kb.adjust(2)
    if isinstance(obj, types.CallbackQuery): await refresh(obj, "<b>Биржи</b>", kb.as_markup())
    else: await obj.answer("<b>Биржи</b>", reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("te_"))
async def te(cb: types.CallbackQuery):
    e = cb.data.split("_")[1]
    u = await get_user_settings(cb.from_user.id)
    try: l = json.loads(u['exchanges'])
    except: l = []
    if e in l:
        if len(l) > 1: l.remove(e)
    else: l.append(e)
    await update_user_setting(cb.from_user.id, "exchanges", json.dumps(l))
    await show_exch(cb)

@router.callback_query(F.data == "menu_rsi")
async def menu_rsi(cb: types.CallbackQuery):
    u = await get_user_settings(cb.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=f"{'✅' if u['rsi_enabled'] else '❌'} Вкл/Выкл", callback_data="trsi")
    if u['rsi_enabled']:
        kb.button(text=f"ТФ: {u.get('rsi_timeframe')}", callback_data="crsi")
        kb.button(text=f"L: <{u['rsi_pump_limit']}", callback_data="ir_p")
        kb.button(text=f"S: >{u['rsi_dump_limit']}", callback_data="ir_d")
    kb.button(text="Назад", callback_data="menu_p_info")
    kb.adjust(1)
    await refresh(cb, "<b>Настройки RSI</b>", kb.as_markup())

@router.callback_query(F.data == "trsi")
async def trsi(cb: types.CallbackQuery):
    u = await get_user_settings(cb.from_user.id)
    await update_user_setting(cb.from_user.id, "rsi_enabled", not u['rsi_enabled'])
    await menu_rsi(cb)

@router.callback_query(F.data == "crsi")
async def crsi(cb: types.CallbackQuery):
    u = await get_user_settings(cb.from_user.id)
    m = ['1m','5m','15m','1h']
    try: i = m.index(u.get('rsi_timeframe','5m'))
    except: i = 1
    await update_user_setting(cb.from_user.id, "rsi_timeframe", m[(i+1)%len(m)])
    await menu_rsi(cb)

@router.callback_query(F.data == "menu_slp")
async def menu_slp(cb: types.CallbackQuery):
    u = await get_user_settings(cb.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=f"{'✅' if u['sleep_enabled'] else '❌'} Вкл/Выкл", callback_data="tslp")
    if u['sleep_enabled']:
        kb.button(text=f"Старт: {u['sleep_from']}:00", callback_data="cslp_f")
        kb.button(text=f"Стоп: {u['sleep_to']}:00", callback_data="cslp_t")
    kb.button(text="Назад", callback_data="settings")
    kb.adjust(1)
    await refresh(cb, "<b>Сон (UTC)</b>", kb.as_markup())

@router.callback_query(F.data == "tslp")
async def tslp(cb: types.CallbackQuery):
    u = await get_user_settings(cb.from_user.id)
    await update_user_setting(cb.from_user.id, "sleep_enabled", not u['sleep_enabled'])
    await menu_slp(cb)

@router.callback_query(F.data.startswith("cslp_"))
async def cslp(cb: types.CallbackQuery):
    t = cb.data.split("_")[1]
    col = f"sleep_{'from' if t=='f' else 'to'}"
    u = await get_user_settings(cb.from_user.id)
    await update_user_setting(cb.from_user.id, col, (u[col]+1)%24)
    await menu_slp(cb)

@router.callback_query(F.data == "menu_int")
async def menu_int(cb: types.CallbackQuery):
    u = await get_user_settings(cb.from_user.id)
    kb = InlineKeyboardBuilder()
    for i in [1,3,5,15,30]:
        s = "✅" if u['interval'] == i else ""
        kb.button(text=f"{i}м {s}", callback_data=f"si_{i}")
    kb.button(text="Ввод", callback_data="ii")
    kb.button(text="Назад", callback_data="settings")
    kb.adjust(3)
    await refresh(cb, f"<b>Интервал: {u['interval']}м</b>", kb.as_markup())

@router.callback_query(F.data.startswith("si_"))
async def si(cb: types.CallbackQuery):
    await update_user_setting(cb.from_user.id, "interval", int(cb.data.split("_")[1]))
    await menu_int(cb)

@router.callback_query(F.data == "menu_thr")
async def menu_thr(cb: types.CallbackQuery):
    u = await get_user_settings(cb.from_user.id)
    kb = InlineKeyboardBuilder()
    for i in [1,2,3,5,10]:
        s = "✅" if u['threshold'] == float(i) else ""
        kb.button(text=f"{i}% {s}", callback_data=f"st_{i}")
    kb.button(text="Ввод", callback_data="it")
    kb.button(text="Назад", callback_data="settings")
    kb.adjust(3)
    await refresh(cb, f"<b>Триггер: {u['threshold']}%</b>", kb.as_markup())

@router.callback_query(F.data.startswith("st_"))
async def st(cb: types.CallbackQuery):
    await update_user_setting(cb.from_user.id, "threshold", float(cb.data.split("_")[1]))
    await menu_thr(cb)

@router.callback_query(F.data.in_({"ii", "it", "ir_p", "ir_d"}))
async def inp(cb: types.CallbackQuery, state: FSMContext):
    m = {"ii":("Мин (1-120):", SettingsState.waiting_for_interval),
         "it":("% (0.1-100):", SettingsState.waiting_for_threshold),
         "ir_p":("RSI Long < (1-99):", SettingsState.waiting_for_rsi_pump),
         "ir_d":("RSI Short > (1-99):", SettingsState.waiting_for_rsi_dump)}
    txt, st = m[cb.data]
    await cb.message.answer(txt)
    await state.set_state(st)
    await cb.answer()

@router.message(SettingsState.waiting_for_interval)
async def fin_i(msg: types.Message, state: FSMContext): await sav(msg, state, "interval", int, 1, 120)
@router.message(SettingsState.waiting_for_threshold)
async def fin_t(msg: types.Message, state: FSMContext): await sav(msg, state, "threshold", float, 0.1, 100)
@router.message(SettingsState.waiting_for_rsi_pump)
async def fin_rp(msg: types.Message, state: FSMContext): await sav(msg, state, "rsi_pump_limit", int, 1, 99)
@router.message(SettingsState.waiting_for_rsi_dump)
async def fin_rd(msg: types.Message, state: FSMContext): await sav(msg, state, "rsi_dump_limit", int, 1, 99)

async def sav(msg, state, col, typ, mn, mx):
    try:
        v = typ(msg.text.replace(',','.'))
        if mn <= v <= mx:
            await update_user_setting(msg.from_user.id, col, v)
            await msg.answer(f"Сохранено: {v}")
        else: await msg.answer("Диапазон!")
    except: await msg.answer("Ошибка!")
    await state.clear()
    await show_set(msg)

@router.message(F.text == "🤝 Рефералка")
async def ref(msg: types.Message, bot: Bot):
    uid = msg.from_user.id
    name = (await bot.get_me()).username
    lnk = f"https://t.me/{name}?start={uid}"
    txt = f"<b>Рефералка</b>\nТвой бонус: +{REFERRER_BONUS_DAYS} дн.\nБонус друга: +{REFERRAL_TRIAL_DAYS-TRIAL_DAYS} дн. к триалу\n\nСсылка:\n<code>{lnk}</code>"
    await msg.answer(txt, parse_mode="HTML")