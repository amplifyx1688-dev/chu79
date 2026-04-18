#!/usr/bin/env python3
import os
import json
import logging
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from pydantic import BaseModel, Field
from typing import List, Optional

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO'))
)
logger = logging.getLogger(__name__)


class ButtonConfig(BaseModel):
    text: str
    url: Optional[str] = None
    callback_data: Optional[str] = None
    color: str = "primary"


class TopicConfig(BaseModel):
    id: int
    name: str
    link: str
    enabled: bool = True
    standard_auto_delete: bool = False
    force_auto_delete: bool = False
    auto_delete_seconds: int = 300
    night_mode: bool = False
    advertising_mode: bool = False
    scheduled_activation: Optional[str] = None
    default_message_text: Optional[str] = None
    default_message_image: Optional[str] = None
    buttons: List[ButtonConfig] = Field(default_factory=list)


class GlobalSettings(BaseModel):
    auto_delete_delay: int = 300
    night_mode_start: str = "22:00"
    night_mode_end: str = "06:00"
    admin_user_ids: List[int] = Field(default_factory=list)


class BotConfig(BaseModel):
    global_settings: GlobalSettings
    topics: List[TopicConfig]


def load_config() -> BotConfig:
    with open('config.json', 'r') as f:
        data = json.load(f)
    return BotConfig(**data)


config = load_config()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
OWNER_ID = int(os.getenv('BOT_OWNER_ID', 0))


def is_night_mode() -> bool:
    now = datetime.now()
    current_time = now.time()
    start_h, start_m = map(int, config.global_settings.night_mode_start.split(':'))
    end_h, end_m = map(int, config.global_settings.night_mode_end.split(':'))
    start_time = datetime.now().replace(hour=start_h, minute=start_m, second=0).time()
    end_time = datetime.now().replace(hour=end_h, minute=end_m, second=0).time()
    
    if start_time < end_time:
        return start_time <= current_time <= end_time
    else:
        return current_time >= start_time or current_time <= end_time


def get_topic_by_id(topic_id: int) -> Optional[TopicConfig]:
    return next((t for t in config.topics if t.id == topic_id), None)


async def auto_delete_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.warning(f"Failed to delete message: {e}")


async def handle_topic_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.is_topic_message:
        return
    
    topic_id = message.message_thread_id
    topic = get_topic_by_id(topic_id)
    
    if not topic or not topic.enabled:
        return
    
    # Night mode check
    if topic.night_mode and is_night_mode():
        await message.delete()
        return
    
    # Auto delete handling
    delete_delay = 0
    if topic.standard_auto_delete and topic.auto_delete_seconds > 0:
        delete_delay = topic.auto_delete_seconds
    if topic.force_auto_delete:
        delete_delay = topic.auto_delete_seconds
    
    if delete_delay > 0:
        asyncio.create_task(auto_delete_message(context, message.chat_id, message.message_id, delete_delay))
    
    # Default message response
    if topic.default_message_text:
        keyboard = []
        row = []
        for btn in topic.buttons:
            button_kwargs = {"text": btn.text}
            if btn.url:
                button_kwargs["url"] = btn.url
            if btn.callback_data:
                button_kwargs["callback_data"] = btn.callback_data
            row.append(InlineKeyboardButton(**button_kwargs))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        reply = await message.reply_text(
            text=topic.default_message_text,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        
        if topic.force_auto_delete:
            asyncio.create_task(auto_delete_message(context, reply.chat_id, reply.message_id, delete_delay))


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    callback_data = query.data
    
    if callback_data == "create_ticket":
        await query.edit_message_text(text="Ticket creation system will be available soon.")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running.")


async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id == OWNER_ID or user_id in config.global_settings.admin_user_ids:
        global config
        config = load_config()
        await update.message.reply_text("Config reloaded successfully.")


def main():
    logger.info("Starting Telegram Bot...")
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CommandHandler('reload', reload_command))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_topic_message))
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    logger.info("Bot started successfully")
    application.run_polling()


if __name__ == '__main__':
    main()
