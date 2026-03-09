import logging
import sqlite3
import math
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = "7618653140:AAFLWh4VFiKb3Ig6c0tQNyEi0byxdhC0Usk"
WEB_APP_URL = "https://geo-bot-site.onrender.com"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db():
    conn = sqlite3.connect('geo_bot.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Пользователи
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_lat REAL,
            last_lng REAL,
            location_updated TIMESTAMP,
            location_denied INTEGER DEFAULT 0
        )
    ''')
    
    # Избранные места
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS favorite_places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            address TEXT,
            lat REAL,
            lng REAL,
            created_at TIMESTAMP
        )
    ''')
    
    # Напоминания
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            place_id INTEGER,
            text TEXT,
            lat REAL,
            lng REAL,
            radius INTEGER DEFAULT 200,
            repeat_type TEXT DEFAULT 'once',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP,
            last_triggered TIMESTAMP,
            expires_at TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")

def haversine(lat1, lon1, lat2, lon2):
    """Расстояние между координатами в метрах"""
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R*c

def calculate_expiration(repeat_type):
    """Вычисляет дату истечения напоминания"""
    now = datetime.now()
    if repeat_type == 'daily':
        return now + timedelta(days=1)
    elif repeat_type == 'weekly':
        return now + timedelta(weeks=1)
    elif repeat_type == 'monthly':
        return now + timedelta(days=30)
    elif repeat_type == 'forever':
        return None  # Никогда не истекает
    else:  # once
        return now + timedelta(days=1)  # Живёт 1 день после срабатывания

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню с инструкцией по геолокации"""
    user = update.effective_user
    
    # Сохраняем пользователя
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, username, first_name, location_denied)
        VALUES (?, ?, ?, 0)
    ''', (user.id, user.username, user.first_name))
    conn.commit()
    conn.close()
    
    # Кнопка с Web App
    keyboard = [[
        InlineKeyboardButton(
            "🗺️ Открыть карту и напоминания",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )
    ]]
    
    # Подробная инструкция по геолокации
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "📍 **КАК ВКЛЮЧИТЬ ГЕОЛОКАЦИЮ:**\n\n"
        "📱 **Android:**\n"
        "1. Настройки Telegram → Конфиденциальность\n"
        "2. Геопозиция → Разрешить доступ → Всегда\n\n"
        "🍎 **iPhone:**\n"
        "1. Настройки телефона → Telegram\n"
        "2. Геопозиция → Всегда\n\n"
        "❓ **Зачем это нужно?**\n"
        "Чтобы я мог напоминать о делах, когда ты рядом с нужным местом,\n"
        "даже если Telegram закрыт!\n\n"
        "👇 **Нажми кнопку, чтобы открыть карту**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка данных из Web App"""
    data = update.effective_message.web_app_data
    if not data:
        return
    
    print(f"📦 Получено: {data.data}")
    
    try:
        payload = json.loads(data.data)
        user_id = update.effective_user.id
        action = payload.get('action')
        
        conn = get_db()
        cursor = conn.cursor()
        
        # ===== ИЗБРАННЫЕ МЕСТА =====
        if action == 'get_places':
            cursor.execute('SELECT * FROM favorite_places WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
            places = cursor.fetchall()
            await update.effective_message.reply_text(
                json.dumps({'type': 'places', 'places': [dict(p) for p in places]}, default=str)
            )
        
        elif action == 'add_place':
            place = payload['place']
            cursor.execute('''
                INSERT INTO favorite_places (user_id, name, address, lat, lng, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, place['name'], place['address'], place['lat'], place['lng'], datetime.now()))
            conn.commit()
            await update.effective_message.reply_text(
                json.dumps({'type': 'success', 'message': '✅ Место сохранено'})
            )
        
        elif action == 'delete_place':
            place_id = payload['place_id']
            cursor.execute('DELETE FROM favorite_places WHERE id = ? AND user_id = ?', (place_id, user_id))
            conn.commit()
            await update.effective_message.reply_text(
                json.dumps({'type': 'success', 'message': '✅ Место удалено'})
            )
        
        # ===== НАПОМИНАНИЯ =====
        elif action == 'get_reminders':
            cursor.execute('''
                SELECT * FROM reminders 
                WHERE user_id = ? AND is_active = 1 
                AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY created_at DESC
            ''', (user_id, datetime.now()))
            reminders = cursor.fetchall()
            await update.effective_message.reply_text(
                json.dumps({'type': 'reminders', 'reminders': [dict(r) for r in reminders]}, default=str)
            )
        
        elif action == 'add_reminder':
            r = payload['reminder']
            expires_at = calculate_expiration(r.get('repeat', 'once'))
            
            cursor.execute('''
                INSERT INTO reminders 
                (user_id, place_id, text, lat, lng, radius, repeat_type, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, 
                r.get('place_id'), 
                r['text'], 
                r['lat'], 
                r['lng'], 
                r.get('radius', 200),
                r.get('repeat', 'once'),
                datetime.now(),
                expires_at
            ))
            conn.commit()
            await update.effective_message.reply_text(
                json.dumps({'type': 'success', 'message': '✅ Напоминание создано'})
            )
        
        # ===== ПРОВЕРКА ГЕОЛОКАЦИИ =====
        elif action == 'check_location':
            lat = payload['lat']
            lng = payload['lng']
            
            # Обновляем позицию пользователя
            cursor.execute('''
                UPDATE users SET last_lat = ?, last_lng = ?, location_updated = ?, location_denied = 0
                WHERE user_id = ?
            ''', (lat, lng, datetime.now(), user_id))
            conn.commit()
            
            # Получаем активные напоминания
            cursor.execute('''
                SELECT * FROM reminders 
                WHERE user_id = ? AND is_active = 1 
                AND (expires_at IS NULL OR expires_at > ?)
            ''', (user_id, datetime.now()))
            
            active_reminders = cursor.fetchall()
            triggered = []
            
            for r in active_reminders:
                distance = haversine(lat, lng, r['lat'], r['lng'])
                
                if distance <= r['radius']:
                    # Проверяем не отправляли ли недавно (для повторяющихся)
                    if not r['last_triggered'] or \
                       (datetime.now() - datetime.fromisoformat(r['last_triggered'])).seconds > 3600:
                        
                        # Обновляем время последнего срабатывания
                        cursor.execute('''
                            UPDATE reminders SET last_triggered = ? WHERE id = ?
                        ''', (datetime.now(), r['id']))
                        
                        # Для одноразовых - деактивируем
                        if r['repeat_type'] == 'once':
                            cursor.execute('''
                                UPDATE reminders SET is_active = 0 WHERE id = ?
                            ''', (r['id'],))
                        
                        conn.commit()
                        
                        # Отправляем уведомление
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"🔔 **НАПОМИНАНИЕ!**\n\n{r['text']}",
                            parse_mode='Markdown'
                        )
                        triggered.append(r['id'])
                        print(f"✅ Отправлено напоминание {r['id']}")
            
            # Очищаем истекшие напоминания
            cursor.execute('''
                UPDATE reminders SET is_active = 0 
                WHERE user_id = ? AND expires_at IS NOT NULL AND expires_at < ?
            ''', (user_id, datetime.now()))
            conn.commit()
            
            print(f"📊 Проверено {len(active_reminders)} напоминаний, отправлено {len(triggered)}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        logger.error(f"Ошибка: {e}")
        await update.effective_message.reply_text(
            json.dumps({'type': 'error', 'message': str(e)})
        )

async def check_expired_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Периодическая проверка истекших напоминаний"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Деактивируем истекшие
    cursor.execute('''
        UPDATE reminders SET is_active = 0 
        WHERE expires_at IS NOT NULL AND expires_at < ?
    ''', (datetime.now(),))
    
    affected = cursor.rowcount
    if affected > 0:
        print(f"🧹 Деактивировано {affected} истекших напоминаний")
    
    conn.commit()
    conn.close()

async def notify_location_denied(context: ContextTypes.DEFAULT_TYPE):
    """Уведомление пользователей, которые отключили геолокацию"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Находим пользователей с активными напоминаниями, но без геолокации
    cursor.execute('''
        SELECT DISTINCT u.user_id, u.first_name 
        FROM users u
        JOIN reminders r ON u.user_id = r.user_id
        WHERE r.is_active = 1 AND u.location_denied = 1
    ''')
    
    users = cursor.fetchall()
    conn.close()
    
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user['user_id'],
                text="⚠️ **ВНИМАНИЕ!**\n\n"
                     "У тебя есть активные напоминания, но геолокация отключена!\n\n"
                     "📍 **Как включить:**\n"
                     "Android: Настройки Telegram → Конфиденциальность → Геопозиция → Всегда\n"
                     "iPhone: Настройки → Telegram → Геопозиция → Всегда\n\n"
                     "После включения я снова смогу напоминать о делах.",
                parse_mode='Markdown'
            )
            print(f"📨 Напоминание о геолокации отправлено пользователю {user['user_id']}")
        except:
            pass

def main():
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Хендлеры
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data))
    
    # Периодические задачи
    job_queue = app.job_queue
    if job_queue:
        # Проверка истекших напоминаний каждый час
        job_queue.run_repeating(check_expired_reminders, interval=3600, first=10)
        # Напоминание о геолокации раз в день в 12:00
        job_queue.run_daily(notify_location_denied, time=datetime.time(12, 0, 0))
        print("⏰ Job queue настроен")
    
    print("🚀 Бот запущен!")
    print("⏰ Проверка геолокации активна")
    print("📅 Истекшие напоминания будут удаляться автоматически")
    app.run_polling()

if __name__ == "__main__":
    main()

