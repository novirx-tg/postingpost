from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from database import Database

router = Router()

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="✍️ Создать пост"), KeyboardButton(text="📢 Мои каналы")],
        [KeyboardButton(text="📅 Отложенные посты"), KeyboardButton(text="📜 История постов")],
        [KeyboardButton(text="❓ Справка")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

@router.message(CommandStart())
async def cmd_start(message: Message, db: Database):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""
    
    # Save user to DB
    await db.add_user(user_id, username, first_name)
    
    welcome_text = (
        f"Привет, {first_name}! 👋\n\n"
        "Я бот для постинга в твои Telegram-каналы.\n\n"
        "С моей помощью ты можешь:\n"
        "• Добавлять свои каналы\n"
        "• Создавать посты с медиагруппами (альбомами до 10 фото/видео)\n"
        "• Располагать текст <b>НАД</b> медиа или под ним\n"
        "• Прятать медиа под интерактивный <b>блюр-спойлер</b>\n"
        "• Добавлять URL-кнопки и кнопки быстрого <b>копирования промокода</b>\n"
        "• Настраивать интерактивные реакции-голосования\n"
        "• Планировать публикации на нужное время\n\n"
        "Для начала добавь хотя бы один канал в разделе «📢 Мои каналы»."
    )
    
    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard())

@router.message(F.text == "❓ Справка")
async def cmd_help(message: Message):
    help_text = (
        "ℹ️ <b>Справка по боту v1.0.2</b>\n\n"
        "<b>📢 Добавление канала:</b>\n"
        "Перейдите в «Мои каналы» -> «➕ Добавить канал». Выберите канал, в котором вы являетесь создателем или администратором. "
        "Убедитесь, что боту выданы права на публикацию сообщений.\n\n"
        "<b>✍️ Создание поста:</b>\n"
        "1. Нажмите «Создать пост» и выберите канал.\n"
        "2. Отправьте текст или медиафайл (фото, видео, альбом, кружок, файл, аудио).\n"
        "3. <b>Новые фичи Bot API:</b>\n"
        "   • <b>Текст Сверху / Снизу</b> — переключайте отображение подписи над картинкой или под ней!\n"
        "   • <b>Блюр-спойлер</b> — скрывайте медиафайлы под интригующий спойлер.\n"
        "   • <b>Кнопки копирования</b> — формат <code>copy:Текст кнопки:Текст для копирования</code> для мгновенного копирования в буфер обмена!\n"
        "   • <b>Превью ссылок</b> — выбор показа ссылки над текстом, компактного вида или отключения.\n"
        "4. Выберите «Опубликовать сейчас» или «Отложить публикацию».\n\n"
        "<b>📅 Отложенные посты:</b>\n"
        "Просмотр, редактирование и отмена запланированных публикаций."
    )
    await message.answer(help_text, parse_mode="HTML")
