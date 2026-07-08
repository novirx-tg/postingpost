import json
import logging
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, MessageOriginChannel
from aiogram.exceptions import TelegramBadRequest

from database import Database
from handlers.start import get_main_menu_keyboard
from handlers.post_creator import parse_buttons
from services.post_service import build_inline_keyboard

logger = logging.getLogger(__name__)
def get_friendly_error_message(error_str: str) -> str:
    err_lower = error_str.lower()
    if "message_id_invalid" in err_lower or "message to edit not found" in err_lower:
        return "Неверный ID сообщения (MESSAGE_ID_INVALID).\nУбедитесь, что это сообщение было отправлено ИМЕННО ЭТИМ БОТОМ (боты не могут редактировать чужие сообщения) и что оно не было удалено из канала."
    if "message can't be edited" in err_lower:
        return "Сообщение не может быть отредактировано.\nУбедитесь, что сообщение было опубликовано этим ботом и у бота есть права на редактирование сообщений."
    if "message is not modified" in err_lower:
        return "Содержимое сообщения не изменилось (новые текст или кнопки совпадают с текущими)."
    if "chat not found" in err_lower:
        return "Канал не найден. Убедитесь, что бот добавлен в канал как администратор."
    return error_str


router = Router()

class EditPostedPost(StatesGroup):
    input_text = State()
    input_buttons = State()

@router.message(F.text == "📜 История постов")
async def show_posted_history(message: Message, db: Database):
    user_id = message.from_user.id
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.*, c.title as channel_title 
            FROM posts p
            JOIN channels c ON p.channel_id = c.channel_id
            WHERE p.user_id = ? AND p.status = 'posted'
            ORDER BY p.created_at DESC
            LIMIT 10
        """, (user_id,))
        posts = [dict(row) for row in cursor.fetchall()]
        
    if not posts:
        await message.answer("📜 <b>У вас пока нет опубликованных постов в истории.</b>", parse_mode="HTML")
        return
        
    text = "📜 <b>История ваших опубликованных постов (последние 10):</b>\n\nВыберите пост для редактирования на канале:"
    keyboard_rows = []
    for post in posts:
        post_id = post['post_id']
        chan_title = post['channel_title']
        post_text = post.get('text') or ""
        # Create a snippet of the post text
        snippet = post_text[:20] + "..." if len(post_text) > 20 else (post_text or f"Медиа ({post['content_type']})")
        display_name = f"📢 {chan_title}: {snippet}"
        keyboard_rows.append([InlineKeyboardButton(text=display_name, callback_data=f"hist_view:{post_id}")])
        
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("hist_view:"))
async def view_history_post(callback: CallbackQuery, db: Database):
    post_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    
    post = db.get_post(post_id)
    if not post or post['user_id'] != user_id:
        await callback.answer("Пост не найден.")
        return
        
    channels = db.get_channels_by_user(user_id)
    channel = next((c for c in channels if c['channel_id'] == post['channel_id']), None)
    chan_title = channel['title'] if channel else f"ID: {post['channel_id']}"
    
    text = (
        f"📜 <b>Опубликованный пост #{post_id}</b>\n\n"
        f"<b>Канал:</b> {chan_title}\n"
        f"<b>Тип контента:</b> <code>{post['content_type']}</code>\n"
    )
    if post.get('text'):
        preview_text = post['text']
        if len(preview_text) > 300:
            preview_text = preview_text[:300] + "..."
        text += f"\n<b>Текст/Подпись:</b>\n{preview_text}\n"
        
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Изменить текст на канале", callback_data=f"hist_edit_txt:{post_id}"),
            InlineKeyboardButton(text="🔗 Изменить кнопки на канале", callback_data=f"hist_edit_btn:{post_id}")
        ],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="hist_list")]
    ])
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data == "hist_list")
async def back_to_history_list(callback: CallbackQuery, db: Database):
    user_id = callback.from_user.id
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.*, c.title as channel_title 
            FROM posts p
            JOIN channels c ON p.channel_id = c.channel_id
            WHERE p.user_id = ? AND p.status = 'posted'
            ORDER BY p.created_at DESC
            LIMIT 10
        """, (user_id,))
        posts = [dict(row) for row in cursor.fetchall()]
        
    if not posts:
        await callback.message.edit_text("📜 <b>У вас пока нет опубликованных постов в истории.</b>", parse_mode="HTML")
        await callback.answer()
        return
        
    text = "📜 <b>История ваших опубликованных постов (последние 10):</b>\n\nВыберите пост для редактирования на канале:"
    keyboard_rows = []
    for post in posts:
        post_id = post['post_id']
        chan_title = post['channel_title']
        post_text = post.get('text') or ""
        snippet = post_text[:20] + "..." if len(post_text) > 20 else (post_text or f"Медиа ({post['content_type']})")
        display_name = f"📢 {chan_title}: {snippet}"
        keyboard_rows.append([InlineKeyboardButton(text=display_name, callback_data=f"hist_view:{post_id}")])
        
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("hist_edit_txt:"))
async def request_new_text(callback: CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[1])
    await state.update_data(edit_post_id=post_id)
    await state.set_state(EditPostedPost.input_text)
    
    await callback.message.answer(
        "📝 <b>Отправьте новый текст/подпись для поста на канале:</b>\n"
        "Бот обновит текст и сохранит исходное форматирование. Для отмены нажмите «❌ Отменить».",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отменить")]], resize_keyboard=True)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("hist_edit_btn:"))
async def request_new_buttons(callback: CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[1])
    await state.update_data(edit_post_id=post_id)
    await state.set_state(EditPostedPost.input_buttons)
    
    text = (
        "🔗 <b>Изменение URL-кнопок на канале</b>\n\n"
        "Отправьте новые кнопки в формате: <code>Текст кнопки - ссылка</code>.\n"
        "Каждая строка — новый ряд, разделитель кнопок в одном ряду — <code>|</code>.\n\n"
        "Отправьте <code>none</code> для удаления кнопок."
    )
    await callback.message.answer(text, parse_mode="HTML", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отменить")]], resize_keyboard=True))
    await callback.answer()


@router.message(EditPostedPost.input_text)
async def process_new_text(message: Message, state: FSMContext, db: Database, bot: Bot):
    if message.text == "❌ Отменить":
        await state.clear()
        await message.answer("Редактирование отменено.", reply_markup=get_main_menu_keyboard())
        return
        
    new_text = message.html_text
    data = await state.get_data()
    post_id = data['edit_post_id']
    
    # Update text in DB
    db.update_post(post_id, text=new_text)
    
    # Get post & sent mapping
    post = db.get_post(post_id)
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT channel_id, message_id FROM sent_posts WHERE post_id = ?", (post_id,))
        sent_messages = cursor.fetchall()
        
    if not sent_messages:
        await message.answer("❌ Ошибка: В базе данных не найдены привязанные сообщения для этого поста.", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return
        
    success_count = 0
    fail_errors = []
    
    markup = build_inline_keyboard(post, db)
    
    for row in sent_messages:
        channel_id = row[0]
        message_id = row[1]
        try:
            if post['content_type'] == 'text':
                await bot.edit_message_text(
                    chat_id=channel_id,
                    message_id=message_id,
                    text=new_text,
                    reply_markup=markup,
                    parse_mode="HTML"
                )
            else:
                await bot.edit_message_caption(
                    chat_id=channel_id,
                    message_id=message_id,
                    caption=new_text,
                    reply_markup=markup,
                    parse_mode="HTML"
                )
            success_count += 1
        except TelegramBadRequest as e:
            fail_errors.append(get_friendly_error_message(str(e)))
        except Exception as e:
            fail_errors.append(get_friendly_error_message(str(e)))
            
    await state.clear()
    
    if success_count > 0:
        await message.answer(
            f"✅ <b>Пост успешно отредактирован на канале!</b>\n"
            f"Обновлено сообщений: {success_count}.",
            parse_mode="HTML",
            reply_markup=get_main_menu_keyboard()
        )
    else:
        err_msg = "\n".join(fail_errors)
        await message.answer(
            f"❌ <b>Не удалось обновить пост на канале.</b>\n\n"
            f"<b>Причины ошибок:</b>\n<code>{err_msg}</code>\n\n"
            f"<i>Обратите внимание: бот должен оставаться администратором в канале с включенным разрешением «Редактирование сообщений» (Edit Messages).</i>",
            parse_mode="HTML",
            reply_markup=get_main_menu_keyboard()
        )


@router.message(EditPostedPost.input_buttons)
async def process_new_buttons(message: Message, state: FSMContext, db: Database, bot: Bot):
    if message.text == "❌ Отменить":
        await state.clear()
        await message.answer("Редактирование отменено.", reply_markup=get_main_menu_keyboard())
        return
        
    text = message.text.strip()
    data = await state.get_data()
    post_id = data['edit_post_id']
    
    try:
        buttons_json = None
        if text.lower() != 'none':
            buttons = parse_buttons(text)
            buttons_json = json.dumps(buttons)
            
        # Update buttons in DB
        db.update_post(post_id, buttons_json=buttons_json)
        
        # Get post & sent messages
        post = db.get_post(post_id)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT channel_id, message_id FROM sent_posts WHERE post_id = ?", (post_id,))
            sent_messages = cursor.fetchall()
            
        if not sent_messages:
            await message.answer("❌ Ошибка: В базе данных не найдены привязанные сообщения для этого поста.", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return
            
        success_count = 0
        fail_errors = []
        
        markup = build_inline_keyboard(post, db)
        
        for row in sent_messages:
            channel_id = row[0]
            message_id = row[1]
            try:
                await bot.edit_message_reply_markup(
                    chat_id=channel_id,
                    message_id=message_id,
                    reply_markup=markup
                )
                success_count += 1
            except TelegramBadRequest as e:
                fail_errors.append(get_friendly_error_message(str(e)))
            except Exception as e:
                fail_errors.append(get_friendly_error_message(str(e)))
                
        await state.clear()
        
        if success_count > 0:
            await message.answer(
                f"✅ <b>Кнопки поста успешно обновлены на канале!</b>\n"
                f"Обновлено сообщений: {success_count}.",
                parse_mode="HTML",
                reply_markup=get_main_menu_keyboard()
            )
        else:
            err_msg = "\n".join(fail_errors)
            await message.answer(
                f"❌ <b>Не удалось обновить кнопки на канале.</b>\n\n"
                f"<b>Причины ошибок:</b>\n<code>{err_msg}</code>",
                parse_mode="HTML",
                reply_markup=get_main_menu_keyboard()
            )
            
    except ValueError as e:
        await message.answer(f"❌ <b>Ошибка в формате кнопок:</b>\n{e}\n\nПопробуйте еще раз или отправьте <code>none</code>.", parse_mode="HTML")


# 11. Forwarded post handler (Auto-registration and direct editing)
@router.message(F.forward_origin)
async def handle_forwarded_post(message: Message, bot: Bot, db: Database):
    user_id = message.from_user.id
    origin = message.forward_origin
    
    if not isinstance(origin, MessageOriginChannel):
        await message.answer("⚠️ Пожалуйста, перешлите сообщение именно из <b>канала</b>.", parse_mode="HTML")
        return
        
    channel_id = origin.chat.id
    message_id = origin.message_id
    
    # 1. Verify user is admin in that channel
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        if member.status not in ('administrator', 'creator'):
            await message.answer("❌ Вы должны быть администратором в этом канале для редактирования постов.")
            return
    except Exception as e:
        await message.answer("❌ Бот не может получить доступ к этому каналу. Убедитесь, что бот добавлен в канал как администратор.")
        return

    # 2. Make sure channel is registered in DB (auto-register if not)
    user_channels = db.get_channels_by_user(user_id)
    channel_linked = next((c for c in user_channels if c['channel_id'] == channel_id), None)
    
    if not channel_linked:
        try:
            chat = await bot.get_chat(channel_id)
            db.add_channel(channel_id, chat.title or "Channel", chat.username or "", user_id)
            await message.answer(f"📢 Канал «{chat.title}» был автоматически подключен к вашему аккаунту!")
        except Exception:
            db.add_channel(channel_id, "Channel", "", user_id)
            await message.answer("📢 Канал был автоматически подключен к вашему аккаунту!")

    # 3. Check if we already have this post in DB
    post = db.get_post_by_sent_msg(channel_id, message_id)
    
    if not post:
        # Create a new post record so we can edit it
        content_type = None
        media_file_id = None
        text = None
        
        # Determine content type
        if message.text:
            content_type = 'text'
            text = message.html_text
        elif message.photo:
            content_type = 'photo'
            media_file_id = message.photo[-1].file_id
            text = message.html_text
        elif message.video:
            content_type = 'video'
            media_file_id = message.video.file_id
            text = message.html_text
        elif message.document:
            content_type = 'document'
            media_file_id = message.document.file_id
            text = message.html_text
        elif message.audio:
            content_type = 'audio'
            media_file_id = message.audio.file_id
            text = message.html_text
        elif message.voice:
            content_type = 'voice'
            media_file_id = message.voice.file_id
            text = message.html_text
        elif message.animation:
            content_type = 'animation'
            media_file_id = message.animation.file_id
            text = message.html_text
        elif message.sticker:
            content_type = 'sticker'
            media_file_id = message.sticker.file_id
        else:
            await message.answer("❌ Этот формат сообщений не поддерживается для редактирования.")
            return

        post_id = db.create_post(
            user_id=user_id,
            channel_id=channel_id,
            content_type=content_type,
            text=text,
            media_file_id=media_file_id,
            status='posted'
        )
        # Link sent post
        db.add_sent_post(channel_id, message_id, post_id)
        post = db.get_post(post_id)
    else:
        post_id = post['post_id']

    # Show menu to edit
    try:
        chat_info = await bot.get_chat(channel_id)
        chan_title = chat_info.title or "Канал"
    except Exception:
        chan_title = "Канал"
    
    preview_text = (
        f"🎯 <b>Распознан пересланный пост #{post_id}</b>\n\n"
        f"<b>Канал:</b> {chan_title}\n"
        f"<b>Тип контента:</b> <code>{post['content_type']}</code>\n"
    )
    if post.get('text'):
        snippet = post['text']
        if len(snippet) > 300:
            snippet = snippet[:300] + "..."
        preview_text += f"\n<b>Текущий текст/подпись:</b>\n{snippet}\n"
        
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Изменить текст на канале", callback_data=f"hist_edit_txt:{post_id}"),
            InlineKeyboardButton(text="🔗 Изменить кнопки на канале", callback_data=f"hist_edit_btn:{post_id}")
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="hist_cancel_edit")]
    ])
    
    await message.answer(preview_text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data == "hist_cancel_edit")
async def cancel_history_edit(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Редактирование отменено.", reply_markup=get_main_menu_keyboard())
    await callback.answer()
