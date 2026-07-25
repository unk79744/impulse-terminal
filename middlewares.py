from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import get_user_settings
from datetime import datetime
import logging

class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if not user:
            return await handler(event, data)

        if isinstance(event, Message) and event.text and event.text.startswith('/start'):
            return await handler(event, data)
        
        if isinstance(event, CallbackQuery):
            cb_data = event.data
            if cb_data in ('pay', 'invoice', 'check_sub', 'settings_main', 'back_prof') or cb_data.startswith('chk_'):
                return await handler(event, data)

        settings = await get_user_settings(user.id)
        sub_date_str = settings.get('subscription_end_date')
        
        is_expired = True
        if sub_date_str:
            try:
                sub_date = datetime.fromisoformat(sub_date_str)
                if sub_date > datetime.now():
                    is_expired = False
            except: pass

        if is_expired:
            text = "⛔️ <b>Ваша подписка истекла</b>\n\nПродлите доступ к терминалу, чтобы получать сигналы и менять настройки."
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Продлить подписку", callback_data="pay")]
            ])
            
            if isinstance(event, Message):
                await event.answer(text, reply_markup=kb, parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                await event.answer("Подписка истекла!", show_alert=True)
                await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
            return 
            
        return await handler(event, data)