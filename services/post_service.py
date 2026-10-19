import json
import logging
from typing import Optional, List, Union
from aiogram import Bot
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, 
    InputMediaPhoto, InputMediaVideo, InputMediaAudio, InputMediaDocument,
    CopyTextButton, LinkPreviewOptions
)
from aiogram.exceptions import TelegramBadRequest
from database import Database

logger = logging.getLogger(__name__)

async def build_inline_keyboard(post: dict, db: Database) -> Optional[InlineKeyboardMarkup]:
    """
    Builds the inline keyboard for a post combining URL buttons, CopyText buttons,
    and reaction/voting buttons asynchronously.
    """
    keyboard_rows = []
    
    # 1. Add URL and CopyText buttons if present
    if post.get('buttons_json'):
        try:
            url_buttons_structure = json.loads(post['buttons_json'])
            # Format expected: list of lists (rows of buttons)
            for row in url_buttons_structure:
                button_row = []
                for btn in row:
                    kwargs = {"text": btn['text']}
                    if btn.get('url'):
                        kwargs['url'] = btn['url']
                    elif btn.get('copy_text'):
                        kwargs['copy_text'] = CopyTextButton(text=btn['copy_text'])
                    elif btn.get('callback_data'):
                        kwargs['callback_data'] = btn['callback_data']
                    
                    if btn.get('style'):
                        kwargs['style'] = btn['style']
                        
                    button_row.append(InlineKeyboardButton(**kwargs))
                keyboard_rows.append(button_row)
        except Exception as e:
            logger.error(f"Error parsing buttons JSON for post {post.get('post_id')}: {e}")

    # 2. Add reaction buttons if present
    if post.get('reactions_json'):
        try:
            reactions = json.loads(post['reactions_json'])
            post_id = post['post_id']
            # Fetch current reaction counts asynchronously
            counts = await db.get_post_reactions_count(post_id)
            
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
            logger.error(f"Error parsing reactions JSON for post {post.get('post_id')}: {e}")

    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows) if keyboard_rows else None


async def send_post(bot: Bot, db: Database, post_id: int, channel_id: int) -> bool:
    """
    Sends the post to the specified channel.
    Supports single media, media groups (albums), link previews, and caption positioning.
    Returns True if successful, False otherwise.
    """
    post = await db.get_post(post_id)
    if not post:
        logger.error(f"Post {post_id} not found in database.")
        return False
        
    try:
        reply_markup = await build_inline_keyboard(post, db)
        content_type = post.get('content_type', 'text')
        text = post.get('text')
        media_id = post.get('media_file_id')
        parse_mode = post.get('parse_mode') or "HTML"
        show_caption_above_media = bool(post.get('show_caption_above_media', 0))
        has_spoiler = bool(post.get('has_spoiler', 0))
        
        # Link preview options for text messages
        link_preview_options = None
        if post.get('link_preview_options_json'):
            try:
                lpo_data = json.loads(post['link_preview_options_json'])
                link_preview_options = LinkPreviewOptions(**lpo_data)
            except Exception as e:
                logger.warning(f"Error parsing link_preview_options_json: {e}")

        # Check for media group (album)
        album_media = await db.get_post_media(post_id)
        if content_type == 'media_group' or len(album_media) > 1:
            media_list = []
            for idx, item in enumerate(album_media):
                m_type = item.get('media_type', 'photo')
                f_id = item.get('file_id')
                item_spoiler = bool(item.get('has_spoiler', 0)) or has_spoiler
                
                # Caption is attached to the first item
                caption = text if idx == 0 else None
                m_parse_mode = parse_mode if idx == 0 else None
                m_show_above = show_caption_above_media if idx == 0 else None

                if m_type == 'photo':
                    media_list.append(InputMediaPhoto(
                        media=f_id,
                        caption=caption,
                        parse_mode=m_parse_mode,
                        show_caption_above_media=m_show_above,
                        has_spoiler=item_spoiler
                    ))
                elif m_type == 'video':
                    media_list.append(InputMediaVideo(
                        media=f_id,
                        caption=caption,
                        parse_mode=m_parse_mode,
                        show_caption_above_media=m_show_above,
                        has_spoiler=item_spoiler
                    ))
                elif m_type == 'document':
                    media_list.append(InputMediaDocument(
                        media=f_id,
                        caption=caption,
                        parse_mode=m_parse_mode
                    ))
                elif m_type == 'audio':
                    media_list.append(InputMediaAudio(
                        media=f_id,
                        caption=caption,
                        parse_mode=m_parse_mode
                    ))

            if media_list:
                sent_group = await bot.send_media_group(chat_id=channel_id, media=media_list)
                if sent_group:
                    first_msg = sent_group[0]
                    await db.add_sent_post(channel_id, first_msg.message_id, post_id)
                    
                    # If there are inline buttons or reactions, send an attached keyboard message
                    if reply_markup:
                        btn_msg = await bot.send_message(
                            chat_id=channel_id,
                            text="🔗",
                            reply_markup=reply_markup
                        )
                        await db.add_sent_post(channel_id, btn_msg.message_id, post_id)
                        
                    await db.update_post(post_id, status='posted')
                    return True

        message = None
        
        # Paid Media (Telegram Stars) check (Bot API 7.5 - 10.x)
        star_count = int(post.get('star_count') or 0)
        if star_count > 0 and (album_media or media_id):
            from aiogram.types import InputPaidMediaPhoto, InputPaidMediaVideo
            paid_items = []
            if album_media:
                for item in album_media:
                    if item.get('media_type') == 'video':
                        paid_items.append(InputPaidMediaVideo(media=item['file_id']))
                    else:
                        paid_items.append(InputPaidMediaPhoto(media=item['file_id']))
            elif media_id:
                if content_type == 'video':
                    paid_items.append(InputPaidMediaVideo(media=media_id))
                else:
                    paid_items.append(InputPaidMediaPhoto(media=media_id))
                    
            if paid_items:
                message = await bot.send_paid_media(
                    chat_id=channel_id,
                    star_count=star_count,
                    media=paid_items,
                    caption=text,
                    parse_mode=parse_mode,
                    show_caption_above_media=show_caption_above_media,
                    reply_markup=reply_markup
                )
                if message:
                    await db.add_sent_post(channel_id, message.message_id, post_id)
                    await db.update_post(post_id, status='posted')
                    return True


        # Native Polls & Quizzes check (Bot API 9.6 - 10.x)
        if content_type == 'poll' and post.get('poll_data_json'):
            try:
                pdata = json.loads(post['poll_data_json'])
                message = await bot.send_poll(
                    chat_id=channel_id,
                    question=pdata['question'],
                    options=pdata['options'],
                    is_anonymous=pdata.get('is_anonymous', True),
                    type=pdata.get('type', 'regular'),
                    allows_multiple_answers=pdata.get('allows_multiple_answers', False),
                    allows_revoting=pdata.get('allows_revoting', True),
                    shuffle_options=pdata.get('shuffle_options', False),
                    description=pdata.get('description'),
                    reply_markup=reply_markup
                )
                if message:
                    await db.add_sent_post(channel_id, message.message_id, post_id)
                    await db.update_post(post_id, status='posted')
                    return True
            except Exception as pe:
                logger.error(f"Failed to send poll for post {post_id}: {pe}")

        if content_type == 'text':
            kwargs = {
                "chat_id": channel_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup
            }
            if link_preview_options is not None:
                kwargs["link_preview_options"] = link_preview_options
            message = await bot.send_message(**kwargs)

        elif content_type == 'photo':
            message = await bot.send_photo(
                chat_id=channel_id,
                photo=media_id,
                caption=text,
                parse_mode=parse_mode,
                show_caption_above_media=show_caption_above_media,
                has_spoiler=has_spoiler,
                reply_markup=reply_markup
            )
        elif content_type == 'video':
            message = await bot.send_video(
                chat_id=channel_id,
                video=media_id,
                caption=text,
                parse_mode=parse_mode,
                show_caption_above_media=show_caption_above_media,
                has_spoiler=has_spoiler,
                reply_markup=reply_markup
            )
        elif content_type == 'animation':
            message = await bot.send_animation(
                chat_id=channel_id,
                animation=media_id,
                caption=text,
                parse_mode=parse_mode,
                show_caption_above_media=show_caption_above_media,
                has_spoiler=has_spoiler,
                reply_markup=reply_markup
            )
        elif content_type == 'document':
            message = await bot.send_document(
                chat_id=channel_id,
                document=media_id,
                caption=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        elif content_type == 'audio':
            message = await bot.send_audio(
                chat_id=channel_id,
                audio=media_id,
                caption=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        elif content_type == 'voice':
            message = await bot.send_voice(
                chat_id=channel_id,
                voice=media_id,
                caption=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        elif content_type == 'video_note':
            message = await bot.send_video_note(
                chat_id=channel_id,
                video_note=media_id,
                reply_markup=reply_markup
            )
            if text:
                await bot.send_message(
                    chat_id=channel_id,
                    text=text,
                    parse_mode=parse_mode
                )
        elif content_type == 'sticker':
            message = await bot.send_sticker(
                chat_id=channel_id,
                sticker=media_id,
                reply_markup=reply_markup
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

        if message:
            await db.add_sent_post(channel_id, message.message_id, post_id)
            await db.update_post(post_id, status='posted')
            return True
            
    except Exception as e:
        logger.error(f"Failed to send post {post_id} to channel {channel_id}: {e}")
        await db.update_post(post_id, status='failed')
        return False
        
    return False
