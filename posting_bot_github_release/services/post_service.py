import json
import logging
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import Database

logger = logging.getLogger(__name__)

def build_inline_keyboard(post: dict, db: Database) -> InlineKeyboardMarkup:
    """
    Builds the inline keyboard for a post combining URL buttons and reaction/voting buttons.
    """
    keyboard_rows = []
    
    # 1. Add URL buttons if present
    if post.get('buttons_json'):
        try:
            url_buttons_structure = json.loads(post['buttons_json'])
            # Format expected: list of lists (rows of buttons)
            for row in url_buttons_structure:
                button_row = []
                for btn in row:
                    kwargs = {"text": btn['text'], "url": btn['url']}
                    if btn.get('style'):
                        kwargs['style'] = btn['style']
                    button_row.append(InlineKeyboardButton(**kwargs))
                keyboard_rows.append(button_row)
        except Exception as e:
            logger.error(f"Error parsing URL buttons JSON for post {post['post_id']}: {e}")

    # 2. Add reaction buttons if present
    if post.get('reactions_json'):
        try:
            reactions = json.loads(post['reactions_json'])
            post_id = post['post_id']
            # Fetch current reaction counts
            counts = db.get_post_reactions_count(post_id)
            
            reaction_row = []
            for emoji in reactions:
                cnt = counts.get(emoji, 0)
                btn_text = f"{emoji} {cnt}" if cnt > 0 else emoji
                # Callback format: vote:post_id:emoji
                reaction_row.append(InlineKeyboardButton(
                    text=btn_text, 
                    callback_data=f"vote:{post_id}:{emoji}"
                ))
            keyboard_rows.append(reaction_row)
        except Exception as e:
            logger.error(f"Error parsing reactions JSON for post {post['post_id']}: {e}")

    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows) if keyboard_rows else None


async def send_post(bot: Bot, db: Database, post_id: int, channel_id: int) -> bool:
    """
    Sends the post to the specified channel.
    Returns True if successful, False otherwise.
    """
    post = db.get_post(post_id)
    if not post:
        logger.error(f"Post {post_id} not found in database.")
        return False
        
    try:
        reply_markup = build_inline_keyboard(post, db)
        content_type = post.get('content_type', 'text')
        text = post.get('text')
        media_id = post.get('media_file_id')
        
        # Parse formatting mode. Using HTML by default for links, bold, etc.
        parse_mode = post.get('parse_mode') or "HTML"
        
        extra_kwargs = {}
            
        message = None
        
        from aiogram.exceptions import TelegramBadRequest
        
        for attempt in (1, 2):
            try:
                if content_type == 'text':
                    message = await bot.send_message(
                        chat_id=channel_id,
                        text=text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                        **extra_kwargs
                    )
                elif content_type == 'photo':
                    message = await bot.send_photo(
                        chat_id=channel_id,
                        photo=media_id,
                        caption=text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                        **extra_kwargs
                    )
                elif content_type == 'video':
                    message = await bot.send_video(
                        chat_id=channel_id,
                        video=media_id,
                        caption=text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                        **extra_kwargs
                    )
                elif content_type == 'document':
                    message = await bot.send_document(
                        chat_id=channel_id,
                        document=media_id,
                        caption=text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                        **extra_kwargs
                    )
                elif content_type == 'audio':
                    message = await bot.send_audio(
                        chat_id=channel_id,
                        audio=media_id,
                        caption=text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                        **extra_kwargs
                    )
                elif content_type == 'voice':
                    message = await bot.send_voice(
                        chat_id=channel_id,
                        voice=media_id,
                        caption=text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                        **extra_kwargs
                    )
                elif content_type == 'animation':
                    message = await bot.send_animation(
                        chat_id=channel_id,
                        animation=media_id,
                        caption=text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                        **extra_kwargs
                    )
                elif content_type == 'sticker':
                    message = await bot.send_sticker(
                        chat_id=channel_id,
                        sticker=media_id,
                        reply_markup=reply_markup,
                        **extra_kwargs
                    )
                    if text:
                        await bot.send_message(
                            chat_id=channel_id,
                            text=text,
                            parse_mode=parse_mode
                        )
                else:
                    logger.error(f"Unsupported content type: {content_type}")
                    return False
                break # Success, exit loop
            except TelegramBadRequest as e:
                if attempt == 1 and "message effects" in str(e).lower() and 'message_effect_id' in extra_kwargs:
                    logger.warning(f"Message effects not supported in channel {channel_id}. Retrying without effect.")
                    del extra_kwargs['message_effect_id']
                    continue
                else:
                    raise e
            
        if message:
            # Map channel message to post_id
            db.add_sent_post(channel_id, message.message_id, post_id)
            db.update_post(post_id, status='posted')
            return True
            
    except Exception as e:
        logger.error(f"Failed to send post {post_id} to channel {channel_id}: {e}")
        db.update_post(post_id, status='failed')
        return False
        
    return False
