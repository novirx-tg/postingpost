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
    db.add_user(user_id, username, first_name)
    
    welcome_text = (
        f"Привет, {first_name}! 👋\n\n"
        "Я бот для постинга в твои Telegram-каналы.\n\n"
        "С моей помощью ты можешь:\n"
        "• Добавлять свои каналы\n"
        "• Создавать посты с текстом, медиа, URL-кнопками и реакциями\n"
        "• Планировать публикации на нужное время\n\n"
        "Для начала добавь хотя бы один канал в разделе «📢 Мои каналы»."
    )
    
    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard())

@router.message(F.text == "❓ Справка")
async def cmd_help(message: Message):
    help_text = (
        "ℹ️ <b>Справка по боту</b>\n\n"
        "<b>📢 Добавление канала:</b>\n"
        "Перейдите в «Мои каналы» -> «➕ Добавить канал». Бот предложит выбрать ваш канал. "
        "Убедитесь, что бот добавлен в канал в качестве администратора с правом публикации сообщений.\n\n"
        "<b>✍️ Создание поста:</b>\n"
        "1. Нажмите «Создать пост» и выберите нужный канал.\n"
        "2. Отправьте текст, картинку, видео, документ, аудио, стикер или гифку.\n"
        "3. Добавьте URL-кнопки (формат: <code>Текст кнопки - ссылка</code>).\n"
        "4. Добавьте реакция-кнопки (например, 👍 👎 🔥).\n"
        "5. Выберите «Опубликовать сейчас» или «Отложить публикацию».\n\n"
        "<b>📅 Отложенные посты:</b>\n"
        "Вы можете посмотреть список запланированных постов, изменить их время или удалить."
    )
    await message.answer(help_text, parse_mode="HTML")
