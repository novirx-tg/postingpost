import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.exceptions import TelegramBadRequest

from database import Database
from handlers.start import get_main_menu_keyboard
from services.post_service import send_post, build_inline_keyboard
from services.scheduler_service import SchedulerService
from services.table_service import convert_markdown_tables_in_text, render_table, parse_markdown_table, extract_text_and_table_from_message

logger = logging.getLogger(__name__)
router = Router()

class PostCreator(StatesGroup):
    select_channel = State()
    input_content = State()
    edit_post = State()
    input_buttons = State()
    input_reactions = State()
    input_schedule_time = State()
    input_table = State()

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отменить создание")]],
        resize_keyboard=True
    )

# 1. Start post creation
@router.message(F.text == "✍️ Создать пост")
async def start_post_creation(message: Message, state: FSMContext, db: Database):
    await state.clear()
    user_id = message.from_user.id
    channels = db.get_channels_by_user(user_id)
    
    if not channels:
        await message.answer(
            "❌ <b>У вас нет подключенных каналов.</b>\n"
            "Пожалуйста, сначала добавьте канал в разделе «📢 Мои каналы».",
            parse_mode="HTML"
        )
        return
        
    text = "✍️ <b>Выберите канал для публикации:</b>"
    keyboard_rows = []
    for chan in channels:
        title = chan['title']
        username = chan['username']
        display_name = f"{title} (@{username})" if username else title
        keyboard_rows.append([InlineKeyboardButton(text=display_name, callback_data=f"post_chan:{chan['channel_id']}")])
        
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await message.answer(text, parse_mode="HTML", reply_markup=markup)
    await state.set_state(PostCreator.select_channel)


# 2. Channel selected
@router.callback_query(PostCreator.select_channel, F.data.startswith("post_chan:"))
async def channel_selected(callback: CallbackQuery, state: FSMContext, db: Database):
    channel_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    
    # Check if user has access to channel
    channels = db.get_channels_by_user(user_id)
    channel = next((c for c in channels if c['channel_id'] == channel_id), None)
    
    if not channel:
        await callback.answer("Канал не найден или у вас нет прав.", show_alert=True)
        return
        
    await state.update_data(
        channel_id=channel_id,
        channel_title=channel['title']
    )
    
    await callback.message.delete()
    await callback.message.answer(
        f"Selected channel: <b>{channel['title']}</b>\n\n"
        "📥 <b>Отправьте содержимое поста.</b>\n"
        "Это может быть обычный текст, картинка, видео, документ, аудио, гифка или стикер.\n"
        "Бот сохранит исходное форматирование текста.",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(PostCreator.input_content)


# 3. Content received
@router.message(PostCreator.input_content)
@router.message(PostCreator.edit_post)
async def content_received(message: Message, state: FSMContext):
    data = await state.get_data()
    existing_content_type = data.get('content_type')
    existing_media_file_id = data.get('media_file_id')
    existing_text = data.get('text')
    
    content_type = None
    media_file_id = None
    text = None
    
    extracted_text, extracted_table = extract_text_and_table_from_message(message)
    
    # 1. Media formats check first
    if message.photo:
        content_type = 'photo'
        media_file_id = message.photo[-1].file_id
        text = message.html_text if message.html_text else (extracted_text or existing_text)
    elif message.video:
        content_type = 'video'
        media_file_id = message.video.file_id
        text = message.html_text if message.html_text else (extracted_text or existing_text)
    elif message.document:
        content_type = 'document'
        media_file_id = message.document.file_id
        text = message.html_text if message.html_text else (extracted_text or existing_text)
    elif message.animation:
        content_type = 'animation'
        media_file_id = message.animation.file_id
        text = message.html_text if message.html_text else (extracted_text or existing_text)
    elif message.audio:
        content_type = 'audio'
        media_file_id = message.audio.file_id
        text = message.html_text if message.html_text else (extracted_text or existing_text)
    elif message.voice:
        content_type = 'voice'
        media_file_id = message.voice.file_id
        text = message.html_text if message.html_text else (extracted_text or existing_text)
    elif message.video_note:
        content_type = 'video_note'
        media_file_id = message.video_note.file_id
        text = message.html_text if message.html_text else (extracted_text or existing_text)
    elif message.sticker:
        content_type = 'sticker'
        media_file_id = message.sticker.file_id
        text = extracted_text or existing_text
    elif getattr(message, 'paid_media', None):
        pm = message.paid_media
        if hasattr(pm, 'photos') and pm.photos:
            content_type = 'photo'
            media_file_id = pm.photos[-1].file_id
        elif hasattr(pm, 'videos') and pm.videos:
            content_type = 'video'
            media_file_id = pm.videos[-1].file_id
        text = message.html_text if message.html_text else (extracted_text or existing_text)

    # 2. Interactive / Specialty types (Polls, Locations, Contacts, Games, Dice)
    elif message.poll:
        content_type = 'text'
        poll = message.poll
        options_text = "\n".join([f"🔹 {opt.text}" for opt in poll.options])
        text = f"📊 <b>{poll.question}</b>\n\n{options_text}"
    elif message.location or message.venue:
        content_type = 'text'
        loc = message.location
        venue = message.venue
        if venue:
            text = f"📍 <b>{venue.title}</b>\n{venue.address}\n<i>(Координаты: {loc.latitude}, {loc.longitude})</i>"
        else:
            text = f"📍 <b>Локация:</b> <code>{loc.latitude}, {loc.longitude}</code>"
    elif message.contact:
        content_type = 'text'
        c = message.contact
        name = f"{c.first_name} {c.last_name or ''}".strip()
        text = f"👤 <b>Контакт:</b> {name}\n📞 <code>{c.phone_number}</code>"
    elif message.dice:
        content_type = 'text'
        text = f"🎲 <b>Значение:</b> {message.dice.value}"

    # 3. Text, Rich Messages, and Universal Fallback
    else:
        if existing_media_file_id and existing_content_type and existing_content_type != 'text':
            content_type = existing_content_type
            media_file_id = existing_media_file_id
        else:
            content_type = 'text'

        text = message.html_text if message.html_text else (extracted_text or message.text or message.caption or "")

    # Keep existing formatting buttons/reactions if we are just updating media/text
    buttons = data.get('buttons', [])
    reactions = data.get('reactions', [])
    
    html_text = message.html_text if message.html_text else text
    raw_text = message.text if message.text is not None else (message.caption if message.caption is not None else text)
    
    await state.update_data(
        content_type=content_type,
        media_file_id=media_file_id,
        text=text,
        html_text=html_text,
        raw_text=raw_text,
        buttons=buttons,
        reactions=reactions,
        from_chat_id=message.chat.id,
        source_message_id=message.message_id
    )
    
    await state.set_state(PostCreator.edit_post)
    await show_preview(message, state)


# Helper to construct and show preview
async def show_preview(message: Message, state: FSMContext):
    data = await state.get_data()
    bot = message.bot
    chat_id = message.chat.id
    
    # Clean up old preview message to avoid clutter
    old_preview_id = data.get("preview_message_id")
    if old_preview_id:
        try:
            await bot.delete_message(chat_id, old_preview_id)
        except Exception:
            pass

    parse_mode = data.get('parse_mode') or 'HTML'
    
    # Select which text to use
    if parse_mode == 'HTML':
        text_to_send = data.get('html_text') or data.get('text') or ""
        actual_parse_mode = 'HTML'
    elif parse_mode == 'HTML_MANUAL':
        text_to_send = data.get('raw_text') or data.get('text') or ""
        actual_parse_mode = 'HTML'
    elif parse_mode == 'Markdown':
        text_to_send = data.get('raw_text') or data.get('text') or ""
        actual_parse_mode = 'Markdown'
    elif parse_mode == 'MarkdownV2':
        text_to_send = data.get('raw_text') or data.get('text') or ""
        actual_parse_mode = 'MarkdownV2'
        
    mode_names = {
        'HTML': 'Авто Telegram',
        'HTML_MANUAL': 'Вручную HTML',
        'Markdown': 'Markdown',
        'MarkdownV2': 'MarkdownV2'
    }
    mode_display = mode_names.get(parse_mode, 'Авто Telegram')

    # Construct the inline buttons markup
    keyboard_rows = []
    # 1. URL buttons
    if data.get('buttons'):
        for row in data['buttons']:
            button_row = []
            for btn in row:
                kwargs = {"text": btn['text'], "url": btn['url']}
                if btn.get('style'):
                    kwargs['style'] = btn['style']
                if btn.get('icon_custom_emoji_id'):
                    kwargs['icon_custom_emoji_id'] = btn['icon_custom_emoji_id']
                button_row.append(InlineKeyboardButton(**kwargs))
            keyboard_rows.append(button_row)
            
    # 2. Reactions
    if data.get('reactions'):
        react_row = []
        for emoji in data['reactions']:
            react_row.append(InlineKeyboardButton(text=f"{emoji} 0", callback_data="preview_react_click"))
        keyboard_rows.append(react_row)
        
    # 3. Actions menu
    actions = [
        [
            InlineKeyboardButton(text="🔗 URL-Кнопки", callback_data="post_edit_btn"),
            InlineKeyboardButton(text="😀 Реакции", callback_data="post_edit_react")
        ],
        [
            InlineKeyboardButton(text="📝 Изменить текст", callback_data="post_edit_text"),
            InlineKeyboardButton(text="🖼️ Изменить медиа", callback_data="post_edit_media")
        ],
        [
            InlineKeyboardButton(text="📊 Таблица", callback_data="post_edit_table"),
            InlineKeyboardButton(text=f"ℹ️ Разметка: {mode_display}", callback_data="post_toggle_markup")
        ],
        [
            InlineKeyboardButton(text="📅 Отложить", callback_data="post_schedule"),
            InlineKeyboardButton(text="🚀 Опубликовать сейчас", callback_data="post_publish")
        ],
        [
            InlineKeyboardButton(text="❌ Отменить", callback_data="post_cancel")
        ]
    ]
    keyboard_rows.extend(actions)
    
    preview_markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    content_type = data['content_type']
    media_id = data.get('media_file_id')
    channel_title = data.get('channel_title')
    
    header_raw = f"👀 ПРЕДВЬЮ ПОСТА (канал: {channel_title} | разметка: {mode_display}):"
    
    if actual_parse_mode == 'HTML':
        formatted_text = f"👀 <b>{header_raw}</b>\n\n" + text_to_send
    elif actual_parse_mode == 'Markdown':
        formatted_text = f"*{header_raw}*\n\n" + text_to_send
    elif actual_parse_mode == 'MarkdownV2':
        import re
        escaped_header = re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', header_raw)
        formatted_text = f"*{escaped_header}*\n\n" + text_to_send
        
    sent_msg = None
    try:
        if data.get('from_chat_id') and data.get('source_message_id') and not data.get('text_modified'):
            try:
                sent_msg = await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=data['from_chat_id'],
                    message_id=data['source_message_id'],
                    reply_markup=preview_markup
                )
            except Exception as ce:
                logger.warning(f"copy_message preview failed: {ce}")

        if sent_msg is None:
            if content_type == 'text':
                sent_msg = await bot.send_message(chat_id, formatted_text, parse_mode=actual_parse_mode, reply_markup=preview_markup)
        elif content_type == 'photo':
            sent_msg = await bot.send_photo(chat_id, media_id, caption=formatted_text, parse_mode=actual_parse_mode, reply_markup=preview_markup)
        elif content_type == 'video':
            sent_msg = await bot.send_video(chat_id, media_id, caption=formatted_text, parse_mode=actual_parse_mode, reply_markup=preview_markup)
        elif content_type == 'document':
            sent_msg = await bot.send_document(chat_id, media_id, caption=formatted_text, parse_mode=actual_parse_mode, reply_markup=preview_markup)
        elif content_type == 'audio':
            sent_msg = await bot.send_audio(chat_id, media_id, caption=formatted_text, parse_mode=actual_parse_mode, reply_markup=preview_markup)
        elif content_type == 'voice':
            sent_msg = await bot.send_voice(chat_id, media_id, caption=formatted_text, parse_mode=actual_parse_mode, reply_markup=preview_markup)
        elif content_type == 'video_note':
            sent_msg = await bot.send_video_note(chat_id, media_id, reply_markup=preview_markup)
            if text_to_send:
                await bot.send_message(chat_id, f"📝 <i>Текст под кружком:</i>\n{text_to_send}", parse_mode=actual_parse_mode)
        elif content_type == 'animation':
            sent_msg = await bot.send_animation(chat_id, media_id, caption=formatted_text, parse_mode=actual_parse_mode, reply_markup=preview_markup)
        elif content_type == 'sticker':
            sent_msg = await bot.send_sticker(chat_id, media_id, reply_markup=preview_markup)
            if text_to_send:
                await bot.send_message(chat_id, f"📝 <i>Текст под стикером:</i>\n{text_to_send}", parse_mode=actual_parse_mode)
    except Exception as e:
        logger.error(f"Failed to send formatted preview: {e}")
        warning_header = f"⚠️ <b>ОШИБКА РАЗМЕТКИ ({mode_display}):</b>\n" \
                         f"Убедитесь, что все теги или символы форматирования закрыты и корректны.\n" \
                         f"Ошибка: <code>{e}</code>\n\n" \
                         f"👀 <b>ПРЕДВЬЮ (Обычный текст):</b>\n\n"
        fallback_text = warning_header + (data.get('raw_text') or data.get('text') or "")
        
        if content_type == 'text':
            sent_msg = await bot.send_message(chat_id, fallback_text, parse_mode="HTML", reply_markup=preview_markup)
        else:
            sent_msg = await bot.send_message(chat_id, fallback_text, parse_mode="HTML", reply_markup=preview_markup)
            
    if sent_msg:
        await state.update_data(preview_message_id=sent_msg.message_id)


# Preview button click alert
@router.callback_query(PostCreator.edit_post, F.data == "preview_react_click")
async def preview_react_click(callback: CallbackQuery):
    await callback.answer("В предпросмотре реакция не нажимается.", show_alert=True)


# 4. URL buttons input
@router.callback_query(PostCreator.edit_post, F.data == "post_edit_btn")
async def request_url_buttons(callback: CallbackQuery, state: FSMContext):
    text = (
        "🔗 <b>Добавление URL-кнопок</b>\n\n"
        "Отправьте кнопки в формате: <code>Текст кнопки - ссылка</code>.\n"
        "Каждая кнопка с новой строки. Разделитель кнопок в одном ряду — <code>|</code>.\n\n"
        "🎨 <b>Новые фичи: цвет кнопок!</b>\n"
        "Вы можете задать цвет кнопке, добавив в конце её названия: <code>primary</code> / <code>blue</code> (синяя), <code>success</code> / <code>green</code> (зеленая) или <code>danger</code> / <code>red</code> (красная).\n\n"
        "<b>Примеры:</b>\n"
        "<code>Купить - https://example.com - success</code>\n"
        "<code>Сайт - https://example.org - danger</code>\n\n"
        "Отправьте <code>none</code> для удаления кнопок."
    )
    await callback.message.answer(text, parse_mode="HTML")
    await state.set_state(PostCreator.input_buttons)
    await callback.answer()


@router.message(PostCreator.input_buttons)
async def process_url_buttons(message: Message, state: FSMContext):
    text = message.text.strip()
    
    if text.lower() == 'none':
        await state.update_data(buttons=[])
        await message.answer("✅ URL-кнопки удалены.")
        await state.set_state(PostCreator.edit_post)
        await show_preview(message, state)
        return
        
    try:
        buttons = parse_buttons(text)
        await state.update_data(buttons=buttons)
        await message.answer("✅ URL-кнопки успешно добавлены.")
        await state.set_state(PostCreator.edit_post)
        await show_preview(message, state)
    except ValueError as e:
        await message.answer(f"❌ <b>Ошибка в формате кнопок:</b>\n{e}\n\nПопробуйте еще раз или отправьте <code>none</code> для сброса.", parse_mode="HTML")


def parse_buttons(text: str) -> list:
    import re
    rows = []
    lines = text.strip().split("\n")
    
    color_map = {
        'primary': 'primary',
        'blue': 'primary',
        'success': 'success',
        'green': 'success',
        'danger': 'danger',
        'red': 'danger'
    }
    
    for line in lines:
        if not line.strip():
            continue
        row_buttons = []
        buttons_raw = line.split("|")
        for btn_raw in buttons_raw:
            btn_raw = btn_raw.strip()
            # Match http://, https:// or tg:// URL
            match = re.search(r'(https?://\S+|tg://\S+)', btn_raw)
            if not match:
                raise ValueError("Ссылка не найдена в кнопке. Убедитесь, что она начинается с http://, https:// или tg://")
            url = match.group(1).strip()
            # The text is everything before the url
            name = btn_raw[:match.start()].strip()
            # Clean trailing separator characters like - or —
            name = re.sub(r'\s*[-\u2014]\s*$', '', name).strip()
            
            if not name:
                raise ValueError("Текст кнопки не может быть пустым.")
                
            post_url_part = btn_raw[match.end():].strip()
            style = None
            
            # Split remaining words to search for style settings
            words = re.split(r'[\s\-—|]+', post_url_part)
            for word in words:
                word = word.strip().lower()
                clean_word = word.replace('style:', '').strip()
                if clean_word in color_map:
                    style = color_map[clean_word]
                    
            btn_dict = {"text": name, "url": url}
            if style:
                btn_dict["style"] = style
                
            row_buttons.append(btn_dict)
        rows.append(row_buttons)
    return rows


# 5. Reactions input
@router.callback_query(PostCreator.edit_post, F.data == "post_edit_react")
async def request_reactions(callback: CallbackQuery, state: FSMContext):
    text = (
        "😀 <b>Добавление кнопок-реакций</b>\n\n"
        "Отправьте эмоджи, которые будут отображаться под постом в качестве кнопок.\n"
        "Разделите их пробелом или запятой (максимум 8 эмоджи).\n\n"
        "<b>Пример:</b> <code>👍 👎 🔥</code>\n\n"
        "Отправьте <code>none</code> для удаления реакций."
    )
    await callback.message.answer(text, parse_mode="HTML")
    await state.set_state(PostCreator.input_reactions)
    await callback.answer()


@router.message(PostCreator.input_reactions)
async def process_reactions(message: Message, state: FSMContext):
    text = message.text.strip()
    
    if text.lower() == 'none':
        await state.update_data(reactions=[])
        await message.answer("✅ Реакции удалены.")
        await state.set_state(PostCreator.edit_post)
        await show_preview(message, state)
        return
        
    try:
        reactions = parse_reactions(text)
        await state.update_data(reactions=reactions)
        await message.answer("✅ Кнопки-реакции добавлены.")
        await state.set_state(PostCreator.edit_post)
        await show_preview(message, state)
    except ValueError as e:
        await message.answer(f"❌ <b>Ошибка:</b>\n{e}\n\nПопробуйте еще раз или отправьте <code>none</code>.", parse_mode="HTML")


def parse_reactions(text: str) -> list:
    import re
    raw_list = re.split(r'[\s,\n]+', text.strip())
    reactions = [r for r in raw_list if r]
    
    # Filter only short strings (emojis)
    # Emojis can have variation selectors so we allow length 1 to 8 bytes / characters
    reactions = [r for r in reactions if 1 <= len(r) <= 6]
    
    if not reactions:
        raise ValueError("Не найдено подходящих эмоджи.")
    if len(reactions) > 8:
        reactions = reactions[:8]
    return reactions


# 6. Change text/media during creation
@router.callback_query(PostCreator.edit_post, F.data == "post_edit_text")
async def edit_text_request(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 <b>Отправьте новый текст поста:</b>", parse_mode="HTML")
    await state.set_state(PostCreator.input_content)
    await callback.answer()


@router.callback_query(PostCreator.edit_post, F.data == "post_edit_media")
async def edit_media_request(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🖼️ <b>Отправьте новое медиа (картинку, видео, гифку, стикер, аудио, документ):</b>", parse_mode="HTML")
    await state.set_state(PostCreator.input_content)
    await callback.answer()


# 6.1 Table formatting handlers
@router.callback_query(PostCreator.edit_post, F.data == "post_edit_table")
@router.callback_query(PostCreator.edit_post, F.data.startswith("post_table_format:"))
async def handle_table_menu(callback: CallbackQuery, state: FSMContext):
    if callback.data.startswith("post_table_format:"):
        style = callback.data.split(":")[1]
        data = await state.get_data()
        current_html = data.get('html_text') or data.get('text') or ""
        current_raw = data.get('raw_text') or data.get('text') or ""
        
        new_html = convert_markdown_tables_in_text(current_html, style=style, format_html=True)
        new_raw = convert_markdown_tables_in_text(current_raw, style=style, format_html=False)
        
        await state.update_data(html_text=new_html, raw_text=new_raw, text=new_html)
        await callback.answer("✅ Таблицы в тексте успешно отформатированы!")
        await show_preview(callback.message, state)
        return

    menu_text = (
        "📊 <b>Управление таблицами в посте</b>\n\n"
        "Поддерживается как нативный интерфейс таблиц <b>Telegram Bot API 10.1+ (RichBlockTable)</b>, так и классическое моноширинное форматирование.\n\n"
        "Выберите желаемый стиль таблиц:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌐 Нативная TG (RichBlockTable)", callback_data="post_table_format:box"),
            InlineKeyboardButton(text="📦 Рамка Unicode (┌─┬─┐)", callback_data="post_table_format:box")
        ],
        [
            InlineKeyboardButton(text="📐 ASCII (+---+)", callback_data="post_table_format:ascii"),
            InlineKeyboardButton(text="➕ Вставить новую таблицу", callback_data="post_table_input")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад к превью", callback_data="post_table_back")
        ]
    ])
    await callback.message.answer(menu_text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(PostCreator.edit_post, F.data == "post_table_back")
async def table_back(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await show_preview(callback.message, state)
    await callback.answer()


@router.callback_query(PostCreator.edit_post, F.data == "post_table_input")
async def request_table_input(callback: CallbackQuery, state: FSMContext):
    text = (
        "➕ <b>Добавление таблицы</b>\n\n"
        "Отправьте данные таблицы в формате Markdown или через разделитель <code>|</code>:\n\n"
        "<b>Пример:</b>\n"
        "<code>Товар | Цена | В наличии\n"
        "Яблоки | 100р | Да\n"
        "Груши | 150р | Нет</code>\n\n"
        "Бот сгенерирует красивую моноширинную таблицу и добавит её к вашему тексту."
    )
    await callback.message.answer(text, parse_mode="HTML")
    await state.set_state(PostCreator.input_table)
    await callback.answer()


@router.message(PostCreator.input_table)
async def process_table_input(message: Message, state: FSMContext):
    raw_input = message.text.strip()
    rows = parse_markdown_table(raw_input)
    if not rows:
        lines = [l.strip() for l in raw_input.split("\n") if l.strip()]
        rows = [[cell.strip() for cell in l.split("|")] for l in lines]

    if not rows or len(rows) == 0:
        await message.answer("❌ <b>Не удалось распознать таблицу.</b> Попробуйте еще раз в формате <code>Столбец 1 | Столбец 2</code>.", parse_mode="HTML")
        return

    data = await state.get_data()
    current_html = data.get('html_text') or data.get('text') or ""
    current_raw = data.get('raw_text') or data.get('text') or ""

    table_simple = render_table(rows, style="simple")
    new_html = (current_html + "\n\n" + table_simple) if current_html else table_simple
    new_raw = (current_raw + "\n\n" + table_simple) if current_raw else table_simple

    await state.update_data(
        html_text=new_html, 
        raw_text=new_raw, 
        text=new_html,
        table_matrix=rows
    )
    await message.answer("✅ Таблица успешно добавлена в пост!")
    await state.set_state(PostCreator.edit_post)
    await show_preview(message, state)


# 7. Publish now
@router.callback_query(PostCreator.edit_post, F.data == "post_publish")
async def publish_now(callback: CallbackQuery, state: FSMContext, db: Database, bot: Bot, scheduler_service: SchedulerService):
    data = await state.get_data()
    user_id = callback.from_user.id
    channel_id = data['channel_id']
    edit_post_id = data.get('edit_post_id')
    
    parse_mode = data.get('parse_mode') or 'HTML'
    actual_db_parse_mode = 'HTML' if parse_mode in ('HTML', 'HTML_MANUAL') else parse_mode
    text_to_save = data.get('html_text') if parse_mode == 'HTML' else data.get('raw_text')
    if text_to_save is None:
        text_to_save = data.get('text')
        
    table_matrix_json = json.dumps(data['table_matrix']) if data.get('table_matrix') else None

    if edit_post_id:
        db.update_post(
            edit_post_id,
            content_type=data['content_type'],
            text=text_to_save,
            media_file_id=data.get('media_file_id'),
            buttons_json=json.dumps(data.get('buttons', [])) if data.get('buttons') else None,
            reactions_json=json.dumps(data.get('reactions', [])) if data.get('reactions') else None,
            message_effect_id=data.get('message_effect_id'),
            parse_mode=actual_db_parse_mode,
            status='draft',
            table_matrix_json=table_matrix_json,
            from_chat_id=data.get('from_chat_id'),
            source_message_id=data.get('source_message_id')
        )
        post_id = edit_post_id
        scheduler_service.remove_job(post_id)
    else:
        post_id = db.create_post(
            user_id=user_id,
            channel_id=channel_id,
            content_type=data['content_type'],
            text=text_to_save,
            media_file_id=data.get('media_file_id'),
            buttons_json=json.dumps(data.get('buttons', [])) if data.get('buttons') else None,
            reactions_json=json.dumps(data.get('reactions', [])) if data.get('reactions') else None,
            message_effect_id=data.get('message_effect_id'),
            parse_mode=actual_db_parse_mode,
            status='draft',
            table_matrix_json=table_matrix_json,
            from_chat_id=data.get('from_chat_id'),
            source_message_id=data.get('source_message_id')
        )
    
    success = await send_post(bot, db, post_id, channel_id)
    
    if success:
        await callback.message.answer("🚀 <b>Пост успешно опубликован!</b>", parse_mode="HTML", reply_markup=get_main_menu_keyboard())
        try:
            await callback.message.delete()
        except Exception:
            pass
        await state.clear()
    else:
        await callback.message.answer("❌ <b>Не удалось отправить пост.</b> Проверьте права бота в канале.", parse_mode="HTML")
    
    await callback.answer()


# 8. Cancel button handling
@router.callback_query(F.data == "post_cancel")
async def cancel_creation_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("❌ Создание поста отменено.", reply_markup=get_main_menu_keyboard())
    await callback.answer()


@router.message(F.text == "❌ Отменить создание")
async def cancel_creation_message(message: Message, state: FSMContext):
    data = await state.get_data()
    # Try deleting preview message
    preview_message_id = data.get("preview_message_id")
    if preview_message_id:
        try:
            await message.bot.delete_message(message.chat.id, preview_message_id)
        except Exception:
            pass
            
    await state.clear()
    await message.answer("❌ Создание поста отменено.", reply_markup=get_main_menu_keyboard())


# 9. Schedule post handlers
@router.callback_query(PostCreator.edit_post, F.data == "post_schedule")
async def request_schedule_time(callback: CallbackQuery, state: FSMContext):
    text = (
        "📅 <b>Планирование публикации</b>\n\n"
        "Отправьте дату и время публикации в формате: <code>ДД.ММ.ГГГГ ЧЧ:ММ</code> (по Московскому времени, UTC+3).\n\n"
        "<b>Пример:</b> <code>08.07.2026 18:30</code>"
    )
    await callback.message.answer(text, parse_mode="HTML")
    await state.set_state(PostCreator.input_schedule_time)
    await callback.answer()


@router.message(PostCreator.input_schedule_time)
async def process_schedule_time(message: Message, state: FSMContext, db: Database, scheduler_service: SchedulerService):
    text = message.text.strip()
    
    try:
        local_dt = parse_schedule_time_string(text)
    except ValueError as e:
        await message.answer(f"❌ <b>Ошибка:</b> {e}\n\nПожалуйста, отправьте корректную дату в формате: <code>ДД.ММ.ГГГГ ЧЧ:ММ</code> (например, <code>08.07.2026 18:30</code>).", parse_mode="HTML")
        return
        
    data = await state.get_data()
    user_id = message.from_user.id
    channel_id = data['channel_id']
    edit_post_id = data.get('edit_post_id')
    
    parse_mode = data.get('parse_mode') or 'HTML'
    actual_db_parse_mode = 'HTML' if parse_mode in ('HTML', 'HTML_MANUAL') else parse_mode
    text_to_save = data.get('html_text') if parse_mode == 'HTML' else data.get('raw_text')
    if text_to_save is None:
        text_to_save = data.get('text')
        
    scheduled_at_str = local_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    if edit_post_id:
        db.update_post(
            edit_post_id,
            content_type=data['content_type'],
            text=text_to_save,
            media_file_id=data.get('media_file_id'),
            buttons_json=json.dumps(data.get('buttons', [])) if data.get('buttons') else None,
            reactions_json=json.dumps(data.get('reactions', [])) if data.get('reactions') else None,
            message_effect_id=data.get('message_effect_id'),
            parse_mode=actual_db_parse_mode,
            status='scheduled',
            scheduled_at=scheduled_at_str,
            from_chat_id=data.get('from_chat_id'),
            source_message_id=data.get('source_message_id')
        )
        post_id = edit_post_id
    else:
        post_id = db.create_post(
            user_id=user_id,
            channel_id=channel_id,
            content_type=data['content_type'],
            text=text_to_save,
            media_file_id=data.get('media_file_id'),
            buttons_json=json.dumps(data.get('buttons', [])) if data.get('buttons') else None,
            reactions_json=json.dumps(data.get('reactions', [])) if data.get('reactions') else None,
            message_effect_id=data.get('message_effect_id'),
            parse_mode=actual_db_parse_mode,
            status='scheduled',
            scheduled_at=scheduled_at_str,
            from_chat_id=data.get('from_chat_id'),
            source_message_id=data.get('source_message_id')
        )
    
    scheduler_service.add_job(post_id, channel_id, local_dt)
    
    preview_message_id = data.get("preview_message_id")
    if preview_message_id:
        try:
            await message.bot.delete_message(message.chat.id, preview_message_id)
        except Exception:
            pass
            
    await state.clear()
    
    success_text = (
        f"✅ <b>Пост успешно запланирован!</b>\n\n"
        f"<b>Канал:</b> {data.get('channel_title')}\n"
        f"<b>Время отправки:</b> {text} (по МСК)"
    )
    await message.answer(success_text, parse_mode="HTML", reply_markup=get_main_menu_keyboard())


def parse_schedule_time_string(text: str) -> datetime:
    try:
        dt = datetime.strptime(text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        raise ValueError("Неверный формат даты. Используйте ДД.ММ.ГГГГ ЧЧ:ММ")
        
    try:
        moscow_tz = ZoneInfo("Europe/Moscow")
        dt_with_tz = dt.replace(tzinfo=moscow_tz)
    except Exception as e:
        logger.error(f"Failed to use ZoneInfo: {e}")
        dt_with_tz = dt
        
    local_dt = dt_with_tz.astimezone()
    
    if local_dt <= datetime.now().astimezone():
        raise ValueError("Время публикации должно быть в будущем!")
        
    return local_dt.replace(tzinfo=None)


# 10. Edit scheduled post entry point
@router.callback_query(F.data.startswith("sched_edit:"))
async def edit_scheduled_post(callback: CallbackQuery, state: FSMContext, db: Database):
    post_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    
    post = db.get_post(post_id)
    if not post or post['user_id'] != user_id:
        await callback.answer("Пост не найден.")
        return
        
    channels = db.get_channels_by_user(user_id)
    channel = next((c for c in channels if c['channel_id'] == post['channel_id']), None)
    channel_title = channel['title'] if channel else f"ID: {post['channel_id']}"
    
    buttons = []
    if post.get('buttons_json'):
        try:
            buttons = json.loads(post['buttons_json'])
        except Exception:
            pass
            
    reactions = []
    if post.get('reactions_json'):
        try:
            reactions = json.loads(post['reactions_json'])
        except Exception:
            pass
            
    await state.clear()
    await state.update_data(
        edit_post_id=post_id,
        channel_id=post['channel_id'],
        channel_title=channel_title,
        content_type=post['content_type'],
        text=post.get('text'),
        html_text=post.get('text') if post.get('parse_mode') == 'HTML' else None,
        raw_text=post.get('text') if post.get('parse_mode') != 'HTML' else None,
        buttons=buttons,
        reactions=reactions,
        message_effect_id=post.get('message_effect_id'),
        parse_mode=post.get('parse_mode') or 'HTML'
    )
    
    await state.set_state(PostCreator.edit_post)
    
    try:
        await callback.message.delete()
    except Exception:
        pass
        
    await show_preview(callback.message, state)
    await callback.answer()


# GLOBAL REACTION CLICK HANDLER
@router.callback_query(F.data.startswith("vote:"))
async def handle_reaction_vote(callback: CallbackQuery, db: Database, bot: Bot):
    parts = callback.data.split(":")
    post_id = int(parts[1])
    emoji = parts[2]
    user_id = callback.from_user.id
    
    # Record/toggle vote in DB
    db.add_vote(post_id, user_id, emoji)
    
    # Retrieve the post to check details and rebuild keyboard
    post = db.get_post(post_id)
    if not post:
        await callback.answer("Пост не найден.")
        return
        
    # Rebuild keyboard with updated counts
    markup = build_inline_keyboard(post, db)
    
    # Edit the channel post reply markup
    try:
        await callback.message.edit_reply_markup(reply_markup=markup)
        await callback.answer("Голос учтен!")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            # If fast click or no change
            await callback.answer("Голос учтен!")
        else:
            logger.error(f"Failed to update reaction button counts: {e}")
            await callback.answer("Ошибка при подсчете голоса.")
    except Exception as e:
        logger.error(f"Error handling reaction vote: {e}")
        await callback.answer("Произошла ошибка.")


# 13. Text formatting toggle handler
@router.callback_query(PostCreator.edit_post, F.data == "post_toggle_markup")
async def post_toggle_markup_mode(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current = data.get('parse_mode') or 'HTML'
    
    modes = ['HTML', 'HTML_MANUAL', 'Markdown', 'MarkdownV2']
    next_index = (modes.index(current) + 1) % len(modes)
    next_mode = modes[next_index]
    
    await state.update_data(parse_mode=next_mode)
    
    mode_names = {
        'HTML': 'Авто Telegram (использует форматирование вашего приложения)',
        'HTML_MANUAL': 'Вручную HTML (для ввода тегов <b>, <i>, <a> и т.д.)',
        'Markdown': 'Markdown (для ввода *bold*, _italic_ и т.д.)',
        'MarkdownV2': 'MarkdownV2 (для продвинутого Markdown)'
    }
    await callback.answer(f"Режим изменен на: {mode_names[next_mode]}", show_alert=True)
    await show_preview(callback.message, state)
