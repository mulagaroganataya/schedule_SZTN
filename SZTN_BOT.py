import subprocess
import sys
import os
from pathlib import Path
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Токен из переменных окружения (безопасно для сервера)
BOT_TOKEN = "8649563055:AAHEJP6eXq-q0nOsrFe7PBUIZ6X_q9pWeOY"

ADMIN_ID = 1698452613  # Вставьте свой Telegram ID
PARSER_PATH = Path(__file__).parent / "schedule.py"

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📅 Вывести расписание")],
        [KeyboardButton("📝 Сообщить об ошибке")]
    ]
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
                await update.message.reply_text(day_schedule)
                sent_count += 1
            except Exception as e:
                print(f"Ошибка отправки: {e}")
                try:
                    await update.message.reply_text(day_schedule, parse_mode=None)
                    sent_count += 1
                except:
                    pass

        if sent_count == 0:
            await update.message.reply_text("❌ Не удалось отправить расписание")

    except subprocess.TimeoutExpired:
        await loading_msg.delete()
        await update.message.reply_text("❌ Превышено время ожидания (90 сек)")
    except Exception as e:
        await loading_msg.delete()
        await update.message.reply_text(f"❌ Ошибка: {type(e).__name__}: {e}")

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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if context.user_data.get('waiting_for_report', False):
        await handle_report_message(update, context)
        return

    if text == "📅 Вывести расписание":
        await show_schedule(update, context)
    elif text == "📝 Сообщить об ошибке":
        await report_error(update, context)
    else:
        await update.message.reply_text(
            "Используйте кнопки внизу экрана:\n"
            "📅 Вывести расписание\n"
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

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("cancel", cancel_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("✅ Бот запущен!")
print(f"📁 Файл парсера: {PARSER_PATH}")
app.run_polling()
