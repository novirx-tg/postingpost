import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database import Database
from services.scheduler_service import SchedulerService

logger = logging.getLogger(__name__)
router = Router()

@router.message(F.text == "📅 Отложенные посты")
async def list_scheduled_posts(message: Message, db: Database):
    user_id = message.from_user.id
    posts = db.get_scheduled_posts_by_user(user_id)
    
    if not posts:
        await message.answer("📅 <b>У вас нет запланированных постов.</b>", parse_mode="HTML")
        return
        
    text = "📅 <b>Список ваших запланированных постов:</b>\n\nВыберите пост для просмотра или удаления:"
    keyboard_rows = []
    for post in posts:
        post_id = post['post_id']
        chan_title = post['channel_title']
        sched_time = post['scheduled_at']
        try:
            dt = datetime.strptime(sched_time, "%Y-%m-%d %H:%M:%S")
            time_display = dt.strftime("%d.%m %H:%M")
        except Exception:
            time_display = sched_time
            
        display_name = f"📢 {chan_title} ({time_display})"
        keyboard_rows.append([InlineKeyboardButton(text=display_name, callback_data=f"sched_view:{post_id}")])
        
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("sched_view:"))
async def view_scheduled_post(callback: CallbackQuery, db: Database):
    post_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    
    post = db.get_post(post_id)
    if not post or post['user_id'] != user_id or post['status'] != 'scheduled':
        await callback.answer("Пост не найден или уже опубликован.", show_alert=True)
        return
        
    channels = db.get_channels_by_user(user_id)
    channel = next((c for c in channels if c['channel_id'] == post['channel_id']), None)
    chan_title = channel['title'] if channel else f"ID: {post['channel_id']}"
    
    text = (
        f"📅 <b>Запланированный пост #{post_id}</b>\n\n"
        f"<b>Канал:</b> {chan_title}\n"
        f"<b>Время отправки:</b> <code>{post['scheduled_at']}</code> (по МСК)\n"
        f"<b>Тип контента:</b> <code>{post['content_type']}</code>\n"
    )
    if post.get('text'):
        preview_text = post['text']
        if len(preview_text) > 300:
            preview_text = preview_text[:300] + "..."
        text += f"\n<b>Текст/Подпись:</b>\n{preview_text}\n"
        
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Редактировать пост", callback_data=f"sched_edit:{post_id}")],
        [InlineKeyboardButton(text="🗑️ Отменить публикацию", callback_data=f"sched_del:{post_id}")],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="sched_list")]
    ])
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data == "sched_list")
async def back_to_scheduled_list(callback: CallbackQuery, db: Database):
    user_id = callback.from_user.id
    posts = db.get_scheduled_posts_by_user(user_id)
    
    if not posts:
        await callback.message.edit_text("📅 <b>У вас нет запланированных постов.</b>", parse_mode="HTML")
        await callback.answer()
        return
        
    text = "📅 <b>Список ваших запланированных постов:</b>\n\nВыберите пост для просмотра или удаления:"
    keyboard_rows = []
    for post in posts:
        post_id = post['post_id']
        chan_title = post['channel_title']
        sched_time = post['scheduled_at']
        try:
            dt = datetime.strptime(sched_time, "%Y-%m-%d %H:%M:%S")
            time_display = dt.strftime("%d.%m %H:%M")
        except Exception:
            time_display = sched_time
            
        display_name = f"📢 {chan_title} ({time_display})"
        keyboard_rows.append([InlineKeyboardButton(text=display_name, callback_data=f"sched_view:{post_id}")])
        
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("sched_del:"))
async def delete_scheduled_post(callback: CallbackQuery, db: Database, scheduler_service: SchedulerService):
    post_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    
    post = db.get_post(post_id)
    if not post or post['user_id'] != user_id:
        await callback.answer("Пост не найден.", show_alert=True)
        return
        
    # Remove from APScheduler
    scheduler_service.remove_job(post_id)
    
    # Delete from DB
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM posts WHERE post_id = ?", (post_id,))
        conn.commit()
        
    await callback.answer("Публикация отменена, пост удален.", show_alert=True)
    
    # Refresh list
    posts = db.get_scheduled_posts_by_user(user_id)
    if not posts:
        await callback.message.edit_text("📅 <b>У вас нет запланированных постов.</b>", parse_mode="HTML")
    else:
        text = "📅 <b>Список ваших запланированных постов:</b>\n\nВыберите пост для просмотра или удаления:"
        keyboard_rows = []
        for post in posts:
            post_id = post['post_id']
            chan_title = post['channel_title']
            sched_time = post['scheduled_at']
            try:
                dt = datetime.strptime(sched_time, "%Y-%m-%d %H:%M:%S")
                time_display = dt.strftime("%d.%m %H:%M")
            except Exception:
                time_display = sched_time
                
            display_name = f"📢 {chan_title} ({time_display})"
            keyboard_rows.append([InlineKeyboardButton(text=display_name, callback_data=f"sched_view:{post_id}")])
            
        markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
