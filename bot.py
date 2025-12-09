import logging
import sys
import sqlite3
import re 
from typing import Final, List

# ИМПОРТЫ
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ApplicationBuilder, 
    ContextTypes,
)
# ИСПОЛЬЗУЕМ HTML ВМЕСТО MARKDOWN
from telegram.constants import ParseMode 

# --- КОНФИГУРАЦИЯ ---
TOKEN: Final[str] = "8560220304:AAHt3B9bv8LfaqUjAClOVkpUsmrrg6dgadE"

# ГЛАВНЫЙ АДМИН ID (сюда приходят уведомления о новых заявках)
MAIN_ADMIN_ID: Final[int] = 7907584687 

# СПИСОК ВСЕХ АДМИНОВ (кто может видеть админ-меню и модерировать)
# Включены: 7907584687, 1242288682, 8305624267, 8262824885
ADMIN_IDS: Final[List[int]] = [
    MAIN_ADMIN_ID, 
    1242288682, 
    8305624267, 
    8262824885
]

DB_NAME: Final[str] = 'daddy_alex_db.sqlite'
PAGE_SIZE: Final[int] = 5 

# Включение логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Настройка состояний для ConversationHandler 
(
    SELECTING_JOB_TYPE,
    WAITING_FOR_JOB_TEXT,
    CONFIRM_JOB_APPLICATION,
    WAITING_FOR_PAYOUT_TEXT,
    CONFIRM_PAYOUT,
) = range(5)

# ==============================================================================
# ДОПОЛНИТЕЛЬНАЯ ФУНКЦИЯ: ЭКРАНИРОВАНИЕ HTML
# ==============================================================================

def escape_html(text: str) -> str:
    """
    Экранирует специальные символы HTML: <, >, &
    """
    if not isinstance(text, str):
        text = str(text)
        
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


# ==============================================================================
# 0. ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ
# ==============================================================================

def init_db():
    """Создает таблицы базы данных SQLite, если они не существуют."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            job_type TEXT NOT NULL,
            application_text TEXT NOT NULL,
            submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payout_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            payout_text TEXT NOT NULL,
            submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()

# ==============================================================================
# 1. КЛАВИАТУРЫ
# ==============================================================================

def get_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Генерирует основное меню для пользователя и админа."""
    keyboard = [
        [InlineKeyboardButton("🎯 Оставить заявку на работу", callback_data="start_job_application")],
        [InlineKeyboardButton("💰 Оставить заявку на выплату", callback_data="start_payout_request")],
    ]
    # ПРОВЕРКА: Если user_id есть в списке ADMIN_IDS, показываем админ-меню
    if user_id in ADMIN_IDS:
        keyboard.append(
            [
                InlineKeyboardButton("✉️ Заявки на работу (Админ)", callback_data="admin_view_jobs_0"),
                InlineKeyboardButton("💵 Заявки на выплату (Админ)", callback_data="admin_view_payouts_0"),
            ]
        )
    return InlineKeyboardMarkup(keyboard)

def get_job_selection_keyboard() -> InlineKeyboardMarkup:
    """Генерирует меню выбора направления работы."""
    keyboard = [
        [
            InlineKeyboardButton("🚚 Курьер", callback_data="job_courier"),
            InlineKeyboardButton("📦 Склад", callback_data="job_warehouse"),
            InlineKeyboardButton("📱 Пиар в Тик Токе", callback_data="job_tiktok"),
        ],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="cancel_application")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ==============================================================================
# 2. ОСНОВНЫЕ ОБРАБОТЧИКИ
# ==============================================================================

async def start(update: Update, context) -> int:
    """Отправляет приветственное сообщение и главное меню."""
    user_id = update.effective_user.id
    
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        message = update.message
    
    text = (
        "👋 Добро пожаловать к работе у дяди Александра!\n\n"
        "Для начала работы выберите нужное вам действие."
    )
    
    keyboard = get_main_menu_keyboard(user_id)
    
    if update.callback_query:
        await message.edit_text(text, reply_markup=keyboard)
    else:
        await message.reply_text(text, reply_markup=keyboard)
        
    return ConversationHandler.END

async def cancel_application(update: Update, context) -> int:
    """Отменяет процесс и возвращает в главное меню."""
    query = update.callback_query
    await query.answer()
    
    context.user_data.clear()
    
    await query.edit_message_text("❌ Действие отменено. Возврат в главное меню.", 
                                  reply_markup=get_main_menu_keyboard(query.from_user.id))
    
    return ConversationHandler.END

# ==============================================================================
# 3. ЗАЯВКИ НА РАБОТУ 
# ==============================================================================

def get_job_template(job_key: str, job_title: str) -> str:
    """Генерирует шаблон заявки в зависимости от типа работы."""
    
    escaped_job_title = escape_html(job_title)
    
    base_template = (
        f"📝 Вы выбрали направление: <b>{escaped_job_title}</b>.\n\n"
        "Пожалуйста, заполните и отправьте заявку <b>ОДНИМ сообщением</b> по следующему шаблону:\n"
        "--- Шаблон ---\n"
    )
    
    if job_key == "job_courier":
        template_body = (
            "1. Имя:\n"
            "2. Ваш @Username телеграмма (обязательно после указанного @Username не менять):\n"
            "3. Возраст:\n"
            "4. Город проживания:\n"
            "5. Готовы вложить залог в размере 60$:\n"
        )
    elif job_key == "job_warehouse":
        template_body = (
            "1. Имя:\n"
            "2. Ваш @Username телеграмма (обязательно после указанного @Username не менять):\n"
            "3. Возраст:\n"
            "4. Город проживания:\n"
            "5. В каком месте планируете хранить? (Квартира, гараж, склад):\n"
            "6. Как вы оцениваете безопасность места? ( От 1 до 10 ):\n"
            "7. Готовы вложить залог в размере 200$:\n"
        )
    elif job_key == "job_tiktok":
        template_body = (
            "1. Имя:\n"
            "2. Ваш @Username телеграмма (обязательно после указанного @Username не менять):\n"
            "3. Сколько дней готовы уделить работе? (от 2-х недель):\n"
            "4. Сколько часов в день готовы уделять работе?:\n"
        )
    else:
        template_body = "1. ФИО:\n2. Дополнительная информация:\n"
        
    return base_template + template_body + "-----------------\n"

async def start_job_application_step(update: Update, context) -> int:
    """
    Точка входа в ConversationHandler.
    Отображает меню выбора направления работы.
    """
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "Выберите нужное вам русло:",
        reply_markup=get_job_selection_keyboard()
    )
    return SELECTING_JOB_TYPE

async def job_selection(update: Update, context) -> int:
    """
    Сохраняет выбор и запрашивает текст заявки. 
    ПЕРЕХОДИТ В СЛЕДУЮЩЕЕ СОСТОЯНИЕ.
    """
    query = update.callback_query
    await query.answer()
    
    job_type_map = {
        "job_courier": "Курьер",
        "job_warehouse": "Склад",
        "job_tiktok": "Пиар в Тик Токе"
    }
    job_key = query.data
    job_title = job_type_map.get(job_key, "Неизвестно")

    context.user_data["job_type"] = job_title
    
    template = get_job_template(job_key, job_title) 

    await query.edit_message_text(template, parse_mode=ParseMode.HTML)
    
    return WAITING_FOR_JOB_TEXT

async def receive_job_text(update: Update, context) -> int:
    """Получает текст заявки и запрашивает подтверждение."""
    user_text = update.message.text
    context.user_data["application_text"] = user_text
    
    job_type = context.user_data.get("job_type", "работу")
    
    confirm_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить и отправить", callback_data="confirm_job_application")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_application")],
    ])
    
    escaped_text = escape_html(user_text)
    escaped_job_type = escape_html(job_type)
    
    preview_text = (
        f"<b>Проверьте вашу заявку на {escaped_job_type}</b>:\n\n"
        f"Текст заявки:\n---\n{escaped_text}\n---\n\n"
        "Если все верно, нажмите 'Подтвердить и отправить'."
    )
    
    await update.message.reply_text(
        preview_text,
        reply_markup=confirm_kb,
        parse_mode=ParseMode.HTML 
    )
    
    return CONFIRM_JOB_APPLICATION

async def confirm_job_application(update: Update, context) -> int:
    """Отправляет заявку админу, сохраняет в БД и завершает процесс."""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    data = context.user_data
    
    job_type = data.get("job_type", "Работу")
    application_text = data.get("application_text", "Текст заявки не найден.")
    
    # --- СОХРАНЕНИЕ В БАЗУ ДАННЫХ ---
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO job_applications (user_id, username, job_type, application_text) 
        VALUES (?, ?, ?, ?)
    """, (user.id, user.username or user.full_name, job_type, application_text))
    conn.commit()
    conn.close()
    # ---------------------------------
    
    # Форматирование ссылки в HTML
    user_link = f"<a href='tg://user?id={user.id}'>{escape_html(user.full_name)}</a>"
    
    # ЭКРАНИРУЕМ текст для отправки админу
    escaped_application_text = escape_html(application_text)
    escaped_job_type = escape_html(job_type)
    
    admin_message = (
        "🔥 <b>НОВАЯ ЗАЯВКА НА РАБОТУ!</b> 🔥\n\n"
        f"<b>Направление:</b> {escaped_job_type}\n" 
        f"<b>От пользователя:</b> {user_link} (ID: <code>{user.id}</code>)\n\n"
        f"<b>Текст заявки:</b>\n"
        f"-------------------\n"
        f"{escaped_application_text}\n"
        f"-------------------"
    )

    # Отправка уведомления только ГЛАВНОМУ АДМИНУ
    await context.bot.send_message(
        chat_id=MAIN_ADMIN_ID, 
        text=admin_message, 
        parse_mode=ParseMode.HTML
    )

    await query.edit_message_text(
        "✅ Ваша заявка отправлена дяде Александру на рассмотрение. Мы свяжемся с вами!"
    )
    
    context.user_data.clear()
    return ConversationHandler.END


# ==============================================================================
# 4. ЗАЯВКИ НА ВЫПЛАТУ 
# ==============================================================================

async def start_payout_request(update: Update, context) -> int:
    """
    Точка входа в ConversationHandler.
    Запрашивает текст заявки на выплату, используя новый шаблон.
    """
    query = update.callback_query
    await query.answer()
    
    template = (
        "💰 <b>ЗАЯВКА НА ВЫПЛАТУ</b>\n\n"
        "Для получения выплат нужно заполнить следующее <b>одним сообщением</b>:\n"
        "--- Шаблон ---\n"
        "1. Ваше имя:\n"
        "2. За что получаете оплату (курьер, склад, пиар - выбрать одно из трёх и указать):\n"
        "3. Описание работы (сколько дней работали/держали склад и тд):\n"
        "4. Доказательства (скрин/видео работы):\n"
        "5. Как удобно получить оплату (крипто/карта):\n"
        "-----------------\n"
    )
    
    await query.edit_message_text(template, parse_mode=ParseMode.HTML)
    
    return WAITING_FOR_PAYOUT_TEXT

async def receive_payout_text(update: Update, context) -> int:
    """Получает текст заявки на выплату и запрашивает подтверждение."""
    payout_text = update.message.text
    context.user_data["payout_text"] = payout_text
    
    confirm_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить и отправить", callback_data="confirm_payout")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_application")],
    ])
    
    escaped_payout_text = escape_html(payout_text)
    
    preview_text = (
        f"<b>Проверьте вашу заявку на выплату</b>:\n\n"
        f"Текст заявки:\n---\n{escaped_payout_text}\n---\n\n"
        "Если все верно, нажмите 'Подтвердить и отправить'."
    )
    
    await update.message.reply_text(
        preview_text,
        reply_markup=confirm_kb,
        parse_mode=ParseMode.HTML
    )
    
    return CONFIRM_PAYOUT

async def confirm_payout(update: Update, context) -> int:
    """Отправляет заявку на выплату админу, сохраняет в БД и завершает процесс."""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    payout_text = context.user_data.get("payout_text", "Текст заявки не найден.")
    
    # --- СОХРАНЕНИЕ В БАЗУ ДАННЫХ ---
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO payout_requests (user_id, username, payout_text) 
        VALUES (?, ?, ?)
    """, (user.id, user.username or user.full_name, payout_text))
    conn.commit()
    conn.close()
    # ---------------------------------
    
    # Форматирование ссылки в HTML
    user_link = f"<a href='tg://user?id={user.id}'>{escape_html(user.full_name)}</a>"
    
    # ЭКРАНИРУЕМ текст для отправки админу
    escaped_payout_text = escape_html(payout_text)
    
    admin_message = (
        "💵 <b>НОВАЯ ЗАЯВКА НА ВЫПЛАТУ!</b> 💵\n\n"
        f"<b>От пользователя:</b> {user_link} (ID: <code>{user.id}</code>)\n\n"
        f"<b>Текст заявки:</b>\n"
        f"-------------------\n"
        f"{escaped_payout_text}\n"
        f"-------------------"
    )

    # Отправка уведомления только ГЛАВНОМУ АДМИНУ
    await context.bot.send_message(
        chat_id=MAIN_ADMIN_ID, 
        text=admin_message, 
        parse_mode=ParseMode.HTML
    )

    await query.edit_message_text("✅ Ваша заявка на выплату отправлена и будет обработана.")
    
    context.user_data.clear()
    return ConversationHandler.END

# ==============================================================================
# 5. АДМИН-ПАНЕЛЬ (Проверка, что запрос пришел от АДМИНА)
# ==============================================================================

async def admin_view_jobs(update: Update, context):
    """Отображает список заявок на работу с пагинацией."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    # ПРОВЕРКА: Только если user_id есть в списке ADMIN_IDS
    if user_id not in ADMIN_IDS:
        return 
        
    try:
        if query.data.startswith('jobs_page_'):
            current_page = int(query.data.split('_')[-1])
        elif query.data == 'admin_view_jobs_0':
            current_page = 0
        else:
            return 
    except ValueError:
        current_page = 0
        
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    total_count = cursor.execute("SELECT COUNT(*) FROM job_applications").fetchone()[0]
    
    offset = current_page * PAGE_SIZE
    cursor.execute(f"SELECT id, submitted_at, job_type, username, application_text FROM job_applications ORDER BY id DESC LIMIT {PAGE_SIZE} OFFSET {offset}")
    jobs = cursor.fetchall()
    conn.close()

    total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE 
    text = f"📧 <b>ЗАЯВКИ НА РАБОТУ ({current_page + 1}/{total_pages or 1})</b>\n\n"
    
    if not jobs:
        text += "🤷‍♂️ Нет активных заявок."
    else:
        for i, (id, date, job, user, app_text) in enumerate(jobs):
            summary = app_text.split('\n')[0].replace('\n', ' ') 
            
            escaped_job = escape_html(job)
            escaped_user = escape_html(user or 'Н/Д')
            escaped_summary = escape_html(summary)
            
            text += (
                f"<b>{offset + i + 1}.</b> [{date[5:16]}] - <b>{escaped_job}</b> от {escaped_user}\n"
                f"   <i>Кратко:</i> {escaped_summary}...\n" 
                f"   <code>/view_job_details_{id}</code>\n" 
                f"-----------------------------------------\n"
            )

    buttons = []
    if current_page > 0:
        buttons.append(InlineKeyboardButton("< Назад", callback_data=f"jobs_page_{current_page - 1}"))
    if (current_page + 1) < total_pages:
        buttons.append(InlineKeyboardButton("Вперед >", callback_data=f"jobs_page_{current_page + 1}"))

    keyboard = []
    if buttons:
        keyboard.append(buttons)
    keyboard.append([InlineKeyboardButton("◀️ Меню", callback_data="main_menu")])
    
    pagination_kb = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, 
                                  reply_markup=pagination_kb)


async def admin_view_payouts(update: Update, context):
    """Отображает список заявок на выплату с пагинацией."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # ПРОВЕРКА: Только если user_id есть в списке ADMIN_IDS
    if user_id not in ADMIN_IDS:
        return 

    try:
        if query.data.startswith('payouts_page_'):
            current_page = int(query.data.split('_')[-1])
        elif query.data == 'admin_view_payouts_0':
            current_page = 0
        else:
            return 
    except ValueError:
        current_page = 0

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    total_count = cursor.execute("SELECT COUNT(*) FROM payout_requests").fetchone()[0]
    
    offset = current_page * PAGE_SIZE
    cursor.execute(f"SELECT id, submitted_at, username, payout_text FROM payout_requests ORDER BY id DESC LIMIT {PAGE_SIZE} OFFSET {offset}")
    payouts = cursor.fetchall()
    conn.close()
    
    total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE
    text = f"💰 <b>ЗАЯВКИ НА ВЫПЛАТУ ({current_page + 1}/{total_pages or 1})</b>\n\n"
    
    if not payouts:
        text += "💸 Нет активных заявок."
    else:
        for i, (id, date, user, pay_text) in enumerate(payouts):
            summary = pay_text.split('\n')[0].replace('\n', ' ')
            
            escaped_user = escape_html(user or 'Н/Д')
            escaped_summary = escape_html(summary)
            
            text += (
                f"<b>{offset + i + 1}.</b> [{date[5:16]}] от {escaped_user}\n"
                f"   <i>Сумма:</i> {escaped_summary}\n" 
                f"   <code>/view_payout_details_{id}</code>\n" 
                f"-----------------------------------------\n"
            )

    buttons = []
    if current_page > 0:
        buttons.append(InlineKeyboardButton("< Назад", callback_data=f"payouts_page_{current_page - 1}"))
    if (current_page + 1) < total_pages:
        buttons.append(InlineKeyboardButton("Вперед >", callback_data=f"payouts_page_{current_page + 1}"))
    
    keyboard = []
    if buttons:
        keyboard.append(buttons)
    keyboard.append([InlineKeyboardButton("◀️ Меню", callback_data="main_menu")])

    pagination_kb = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, 
                                  reply_markup=pagination_kb)


async def admin_show_details(update: Update, context):
    """Отображает полную информацию по заявке и кнопки модерации."""
    message = update.message
    
    # ПРОВЕРКА: Только если chat.id есть в списке ADMIN_IDS
    if message.chat.id not in ADMIN_IDS:
        return 

    command = message.text
    parts = command.split('_')
    request_type = parts[1] 
    item_id = int(parts[-1])
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    if request_type == 'job':
        cursor.execute("SELECT id, user_id, username, job_type, application_text, submitted_at FROM job_applications WHERE id = ?", (item_id,))
        data = cursor.fetchone()
        
        if not data:
            await message.reply_text("Заявка на работу не найдена.")
            conn.close()
            return
            
        (id, user_id, username, job_type, application_text, date) = data
        
        user_link = f"<a href='tg://user?id={user_id}'>{escape_html(username or 'Пользователь')}</a>"
        
        escaped_application_text = escape_html(application_text)
        escaped_job_type = escape_html(job_type)

        full_text = (
            f"<b>✅ ДЕТАЛИ ЗАЯВКИ НА РАБОТУ (ID: {id})</b>\n\n"
            f"<b>Дата:</b> {date[:16]}\n"
            f"<b>Направление:</b> {escaped_job_type}\n"
            f"<b>Заявитель:</b> {user_link} (ID: <code>{user_id}</code>)\n"
            f"-----------------------------------------\n"
            f"{escaped_application_text}"
        )
        
    elif request_type == 'payout':
        cursor.execute("SELECT id, user_id, username, payout_text, submitted_at FROM payout_requests WHERE id = ?", (item_id,))
        data = cursor.fetchone()

        if not data:
            await message.reply_text("Заявка на выплату не найдена.")
            conn.close()
            return
            
        (id, user_id, username, payout_text, date) = data
        
        user_link = f"<a href='tg://user?id={user_id}'>{escape_html(username or 'Пользователь')}</a>"
        
        escaped_payout_text = escape_html(payout_text)

        full_text = (
            f"<b>💸 ДЕТАЛИ ЗАЯВКИ НА ВЫПЛАТУ (ID: {id})</b>\n\n"
            f"<b>Дата:</b> {date[:16]}\n"
            f"<b>Заявитель:</b> {user_link} (ID: <code>{user_id}</code>)\n"
            f"-----------------------------------------\n"
            f"{escaped_payout_text}"
        )
        
    conn.close()
    
    moderation_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ ПРИНЯТЬ", callback_data=f"accept_{request_type}_{id}_{user_id}"),
            InlineKeyboardButton("❌ ОТКЛОНИТЬ", callback_data=f"reject_{request_type}_{id}_{user_id}"),
        ],
        [InlineKeyboardButton("⬅️ Назад к списку", callback_data=f"admin_view_{request_type}s_0")],
    ])
    
    await message.reply_text(full_text, parse_mode=ParseMode.HTML, reply_markup=moderation_kb)


async def admin_handle_moderation(update: Update, context):
    """Обрабатывает принятие/отклонение заявки."""
    query = update.callback_query
    await query.answer()
    
    # ПРОВЕРКА: Только если user_id есть в списке ADMIN_IDS
    if query.from_user.id not in ADMIN_IDS:
        return

    parts = query.data.split('_')
    action = parts[0] 
    request_type = parts[1] 
    item_id = int(parts[2])
    target_user_id = int(parts[3])
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. Удаляем заявку из БД после обработки
    table_name = 'job_applications' if request_type == 'job' else 'payout_requests'
    cursor.execute(f"DELETE FROM {table_name} WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()

    # 2. Формируем сообщение для заявителя (с использованием HTML)
    if request_type == 'job':
        if action == 'accept':
            user_message = "🎉 <b>ВАША ЗАЯВКА НА РАБОТУ ПРИНЯТА!</b> 🎉\n\nПоздравляем! Вы можете приступать к работе. Дядя Александр свяжется с вами для дальнейших инструкций."
        else:
            user_message = "❌ <b>Ваша заявка на работу отклонена.</b>\n\nПожалуйста, проверьте правильность заполнения данных и попробуйте снова, или свяжитесь с администратором."
    
    else: # Payout
        if action == 'accept':
            user_message = "✅ <b>ВАША ЗАЯВКА НА ВЫПЛАТУ ПОДТВЕРЖДЕНА!</b>\n\nСредства будут отправлены по указанным реквизитам в ближайшее время."
        else:
            user_message = "❌ <b>Ваша заявка на выплату отклонена.</b>\n\nПроверьте баланс и правильность реквизитов. Если вы считаете, что это ошибка, свяжитесь с администратором."
            
    # 3. Отправляем ответ заявителю
    try:
        await context.bot.send_message(chat_id=target_user_id, text=user_message, parse_mode=ParseMode.HTML)
        moderator_response = f"✅ Заявка ID:{item_id} (<b>{'Принята' if action == 'accept' else 'Отклонена'}</b>) обработана. Ответ отправлен пользователю."
    except Exception as e:
        moderator_response = f"⚠️ Заявка ID:{item_id} (<b>{'Принята' if action == 'accept' else 'Отклонена'}</b>) обработана, но не удалось отправить ответ пользователю {target_user_id}."
        
    # 4. Обновляем сообщение для модератора
    await query.edit_message_text(f"<b>МОДЕРАЦИЯ ЗАВЕРШЕНА</b>\n\n{moderator_response}", parse_mode=ParseMode.HTML)
    
    # 5. Возвращаемся в главное меню
    await query.message.reply_text("Выберите следующее действие:", reply_markup=get_main_menu_keyboard(query.from_user.id))
    
    return ConversationHandler.END 


# ==============================================================================
# 6. ОСНОВНАЯ ФУНКЦИЯ (MAIN)
# ==============================================================================

def main() -> None:
    """Запуск бота."""
    
    init_db()

    try:
        application = Application.builder().token(TOKEN).build()
        
        # 1. ConversationHandler для ЗАЯВОК НА РАБОТУ 
        job_application_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(start_job_application_step, pattern=r"^start_job_application$")],
            states={
                SELECTING_JOB_TYPE: [
                    CallbackQueryHandler(job_selection, pattern=r"^job_")
                ],
                WAITING_FOR_JOB_TEXT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, receive_job_text)
                ],
                CONFIRM_JOB_APPLICATION: [
                    CallbackQueryHandler(confirm_job_application, pattern=r"^confirm_job_application$")
                ],
            },
            fallbacks=[
                CallbackQueryHandler(cancel_application, pattern=r"^cancel_application$"),
                CommandHandler("start", start),
            ],
        )
        
        # 2. ConversationHandler для ЗАЯВОК НА ВЫПЛАТУ 
        payout_request_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(start_payout_request, pattern=r"^start_payout_request$")],
            states={
                WAITING_FOR_PAYOUT_TEXT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, receive_payout_text)
                ]
                ,
                CONFIRM_PAYOUT: [
                    CallbackQueryHandler(confirm_payout, pattern=r"^confirm_payout$")
                ],
            },
            fallbacks=[
                CallbackQueryHandler(cancel_application, pattern=r"^cancel_application$"),
                CommandHandler("start", start),
            ],
        )

        # Добавляем все обработчики
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(start, pattern=r"^main_menu$")) 
        
        # Обработчики, которые используют ConversationHandler
        application.add_handler(job_application_handler)
        application.add_handler(payout_request_handler)
        
        # Админские кнопки: Списки с пагинацией (просмотр заявок)
        application.add_handler(CallbackQueryHandler(admin_view_jobs, pattern=r"^(jobs_page_)\d+$|^admin_view_jobs_0$"))
        application.add_handler(CallbackQueryHandler(admin_view_payouts, pattern=r"^(payouts_page_)\d+$|^admin_view_payouts_0$"))

        # Админские кнопки: Детальный просмотр (команда /view_..._details_123)
        # Убеждаемся, что только один из ADMIN_IDS может отправлять эту команду.
        application.add_handler(MessageHandler(filters.Regex(r'^/view_(job|payout)_details_\d+$') & filters.Chat(chat_id=ADMIN_IDS), admin_show_details))
        
        # Админские кнопки: Модерация (Принять/Отклонить)
        application.add_handler(CallbackQueryHandler(admin_handle_moderation, pattern=r"^(accept|reject)_"))

        logging.info("Bot started polling...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        print("-" * 50)
        print("КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ БОТА:")
        print(f"Тип ошибки: {type(e).__name__}")
        print(f"Сообщение: {e}")
        print("\nПОПРОБУЙТЕ ОБНОВИТЬ БИБЛИОТЕКУ: pip install --upgrade python-telegram-bot")
        print("-" * 50)
        input("Нажмите Enter, чтобы закрыть окно...")


if __name__ == "__main__":
    main()