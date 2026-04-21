import subprocess
import sys
import os
from pathlib import Path
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import asyncio
import re
import json

# Токен из переменных окружения (безопасно для сервера)
BOT_TOKEN = "8649563055:AAHEJP6eXq-q0nOsrFe7PBUIZ6X_q9pWeOY"

ADMIN_ID = 1698452613  # Вставьте свой Telegram ID
PARSER_PATH = Path(__file__).parent / "schedule.py"
SZTN_CHAT_ID = -1003918031419       #<-- сюда ID супергруппы (добавить "-100" в начало ID)
SCHEDULE_THREAD_ID = 6      #<-- сюда ID конкретной ветки

# состояния для изменения (редактирования) расписания
WAITING_DATE, WAITING_NEW_TEXT = range(2)

# для хранения данных расписания в файле. Чтобы были не страшны перезапуски бота
CACHE_FILE = Path(__file__).parent / "schedule_cache.json"

def load_cache():
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            print("⚠️ Ошибка чтения файла кеша. Будет создан новый.")
    return {}

def save_cache(cache_data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"⚠️ Ошибка сохранения кеша: {e}")

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📅 Вывести расписание")],
        [KeyboardButton("✍️ Изменить расписание")],
        [KeyboardButton("📝 Сообщить об ошибке")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# кнопка отмены текущей операции
def get_cancel_keyboard():
    keyboard = [[KeyboardButton("❌ Отмена")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def split_by_dates(text: str):
    """Разбивает расписание по датам"""
    lines = text.split('\n')
    messages = []
    current_message = []
    
    months = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]

    for line in lines:
        if not line.strip() and not current_message:
            continue

        is_date = False
        for month in months:
            if month in line and line and line[0].isdigit():
                is_date = True
                break

        if is_date and current_message:
            full_message = '\n'.join(current_message).strip()
            if full_message:
                messages.append(full_message)
            current_message = [line]
        else:
            current_message.append(line)
    if current_message:
        full_message = '\n'.join(current_message).strip()
        if full_message:
            messages.append(full_message)

    return messages

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 Привет! Я бот с расписанием.\n\n"
        "Используй кнопки внизу экрана:\n"
        "📅 Вывести расписание — получить расписание\n"
        "✍️ Изменить расписание — отредактировать сообщение в группе\n"
        "📝 Сообщить об ошибке — написать администратору"
    )
    await update.message.reply_text(welcome_text, reply_markup=get_main_keyboard())

async def show_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loading_msg = await update.message.reply_text("⏳ Загружаю расписание...")

    try:
        # ГЛАВНОЕ ИЗМЕНЕНИЕ: не указываем кодировку, читаем как байты и декодируем в utf-8
        result = subprocess.run(
            [sys.executable, str(PARSER_PATH)],
            capture_output=True,
            timeout=90
        )

        # Пробуем декодировать вывод в utf-8 (для Linux)
        try:
            stdout_text = result.stdout.decode('utf-8')
        except UnicodeDecodeError:
            # Если не получилось, пробуем cp1251 (для Windows)
            try:
                stdout_text = result.stdout.decode('cp1251')
            except UnicodeDecodeError:
                # Если всё плохо — заменяем непонятные символы
                stdout_text = result.stdout.decode('utf-8', errors='replace')

        stderr_text = result.stderr.decode('utf-8', errors='replace') if result.stderr else ""

        if result.returncode != 0:
            await loading_msg.delete()
            await update.message.reply_text(f"❌ Ошибка при получении расписания (код {result.returncode})")
            if stderr_text:
                print(f"Ошибка парсера: {stderr_text[:500]}")
            return

        if not stdout_text or not stdout_text.strip():
            await loading_msg.delete()
            await update.message.reply_text("❌ Парсер не вернул данных")
            return

        messages_by_date = split_by_dates(stdout_text)

        await loading_msg.delete()

        if not messages_by_date:
            await update.message.reply_text("❌ Не удалось разбить расписание по датам")
            return

        sent_count = 0
        for day_schedule in messages_by_date:
            if not day_schedule or not day_schedule.strip():
                continue

            if len(day_schedule) > 4096:
                day_schedule = day_schedule[:4000] + "\n\n... (текст обрезан)"

            try:
                #await update.message.reply_text(day_schedule)   #заменить на:
                sent_msg = await context.bot.send_message(
                    chat_id=SZTN_CHAT_ID,
                    message_thread_id=SCHEDULE_THREAD_ID,
                    text=day_schedule
                )
                sent_count += 1
                # сохраняем в кеш дату, текст сообщения и message_id
                first_line = day_schedule.split('\n')[0].strip()
                date_part = first_line.split(',')[0].strip().lower()
                if 'schedule_messages' not in context.bot_data:
                    context.bot_data['schedule_messages'] = {}
                context.bot_data['schedule_messages'][date_part] = sent_msg.message_id
                context.bot_data['schedule_messages'][date_part + '_text'] = day_schedule

                # между отправкой сообщений с расписанием пауза 5 секунд
                # нужно, чтобы телеграм не блокировал за флуд (~20 сообщений в минуту предел)
                await asyncio.sleep(3.1)

            except Exception as e:
                print(f"Ошибка отправки: {e}")
                try:
                    await asyncio.sleep(5)
                    #await update.message.reply_text(day_schedule, parse_mode=None)  #Заменить на:
                    await context.bot.send_message(
                        chat_id=SZTN_CHAT_ID,
                        message_thread_id=SCHEDULE_THREAD_ID,
                        text=day_schedule,
                        parse_mode=None
                    )
                    sent_count += 1
                except:
                    pass
        
        # сохраняем кеш в файл после отправки всех сообщений
        save_cache(context.bot_data['schedule_messages'])

        if sent_count == 0:
            await update.message.reply_text("❌ Не удалось отправить расписание")

    except subprocess.TimeoutExpired:
        await loading_msg.delete()
        await update.message.reply_text("❌ Превышено время ожидания (90 сек)")
    except Exception as e:
        await loading_msg.delete()
        await update.message.reply_text(f"❌ Ошибка: {type(e).__name__}: {e}")

async def edit_schedule_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📅 Введите дату в формате 'число месяц', например: 5 апреля\n\n"
        "Для отмены нажмите кнопку «❌ Отмена».",
        reply_markup=get_cancel_keyboard()
    )
    return WAITING_DATE

async def process_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_input = update.message.text.strip()

    if date_input == "❌ Отмена":
        await cancel_edit(update, context)
        return ConversationHandler.END

    normalized = date_input.lower()  # например, "5 апреля"
    
    schedule_messages = context.bot_data.get('schedule_messages', {})
    msg_id = schedule_messages.get(normalized)
    msg_text = schedule_messages.get(normalized + '_text')
    
    if not msg_id or not msg_text:
        await update.message.reply_text("❌ Не найдено расписание на эту дату.\n")
        return ConversationHandler.END
    
    # Сохраняем ID сообщения и дату для следующего шага
    context.user_data['edit_msg_id'] = msg_id
    context.user_data['edit_date_norm'] = normalized   # нормализованная дата (ключ)
    context.user_data['edit_date_raw'] = date_input    # исходный ввод (для красоты)
    
    await update.message.reply_text(
        f"📝 Текущее расписание на {date_input}:\n\n{msg_text}\n\n"
        "✏️ Отправьте **новый** текст сообщения (можно скопировать и изменить).",
        reply_markup=get_cancel_keyboard()
    )
    return WAITING_NEW_TEXT

async def replace_schedule_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_text = update.message.text
    if len(new_text) > 4096:
        await update.message.reply_text("❌ Текст слишком длинный (макс. 4096 символов).")
        return WAITING_NEW_TEXT  # остаёмся в том же состоянии

    if new_text == "❌ Отмена":
        await cancel_edit(update, context)
        return ConversationHandler.END
    
    msg_id = context.user_data.get('edit_msg_id')
    norm_date = context.user_data.get('edit_date_norm')
    
    if not msg_id or not norm_date:
        await update.message.reply_text("❌ Ошибка: не найдены данные о сообщении. Попробуйте заново.")
        return ConversationHandler.END
    
    try:
        # Редактируем сообщение в супергруппе
        await context.bot.edit_message_text(
            chat_id=SZTN_CHAT_ID,
            message_id=msg_id,
            text=new_text,
            api_kwargs={'message_thread_id': SCHEDULE_THREAD_ID}
        )
        # Обновляем кеш в памяти
        context.bot_data['schedule_messages'][norm_date + '_text'] = new_text
        save_cache(context.bot_data['schedule_messages'])
        
        await update.message.reply_text(
            "✅ Расписание успешно обновлено в группе!",
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при замене: {e}")
    
    # Очищаем временные данные
    context.user_data.pop('edit_msg_id', None)
    context.user_data.pop('edit_date_norm', None)
    context.user_data.pop('edit_date_raw', None)
    
    return ConversationHandler.END

async def report_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 Опишите проблему или ошибку одним сообщением.\n"
        "Я перешлю его администратору.\n\n"
        "✏️ Напишите ваше сообщение прямо сейчас:"
    )
    context.user_data['waiting_for_report'] = True

async def handle_report_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('waiting_for_report', False):
        return

    context.user_data['waiting_for_report'] = False
    report_text = update.message.text

    user = update.effective_user
    username = user.username if user.username else "нет username"
    first_name = user.first_name if user.first_name else ""
    last_name = user.last_name if user.last_name else ""
    user_id = user.id

    admin_message = (
        f"📨 *НОВЫЙ РЕПОРТ ОБ ОШИБКЕ*\n\n"
        f"👤 *От пользователя:*\n"
        f"   ID: `{user_id}`\n"
        f"   Username: @{username}\n"
        f"   Имя: {first_name} {last_name}\n\n"
        f"📝 *Сообщение:*\n"
        f"{report_text}"
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message,
            parse_mode="Markdown"
        )
        await update.message.reply_text(
            "✅ Ваше сообщение отправлено администратору.\n"
            "Спасибо за обратную связь!"
        )
    except Exception as e:
        await update.message.reply_text(
            "❌ Не удалось отправить сообщение администратору."
        )
        print(f"Ошибка отправки репорта: {e}")

async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Редактирование отменено.",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if context.user_data.get('waiting_for_report', False):
        await handle_report_message(update, context)
        return

    if text == "📅 Вывести расписание":
        await show_schedule(update, context)
    elif text == "📝 Сообщить об ошибке":
        await report_error(update, context)
    elif text == "✍️ Изменить расписание":
        return
    else:
        await update.message.reply_text(
            "Используйте кнопки внизу экрана:\n"
            "📅 Вывести расписание\n"
            "✍️ Изменить расписание\n"
            "📝 Сообщить об ошибке",
            reply_markup=get_main_keyboard()
        )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_for_report', False):
        context.user_data['waiting_for_report'] = False
        await update.message.reply_text("❌ Отправка сообщения отменена.")
    else:
        await update.message.reply_text("У вас нет активной отправки сообщения.")

# Создаём приложение
app = Application.builder().token(BOT_TOKEN).build()

# Загружаем сохранённый кеш расписаний
app.bot_data['schedule_messages'] = load_cache()
print(f"📦 Загружено {len(app.bot_data['schedule_messages'])} записей кеша")

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("cancel", cancel_command))

# НОВОЕ. Надо для изменения расписания.
# я пока не разбирал вот эту писанину:
edit_conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex('^✍️ Изменить расписание$'), edit_schedule_start)],
    states={
        WAITING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_date)],
        WAITING_NEW_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, replace_schedule_message)],
    },
    fallbacks=[CommandHandler('cancel', cancel_edit)],
)
app.add_handler(edit_conv_handler)
# неразобранная писанина заканчивается тут.

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("✅ Бот запущен!")
print(f"📁 Файл парсера: {PARSER_PATH}")
app.run_polling()