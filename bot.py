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

# ========== БАЗА ДАННЫХ ==========
def get_db():
    conn = sqlite3.connect('geo_bot.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_lat REAL,
            last_lng REAL,
            last_location_update TIMESTAMP
        )
    ''')
    
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
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R*c

def calculate_expiration(repeat_type):
    now = datetime.now()
    if repeat_type == 'daily':
        return now + timedelta(days=1)
    elif repeat_type == 'weekly':
        return now + timedelta(weeks=1)
    elif repeat_type == 'monthly':
        return now + timedelta(days=30)
    elif repeat_type == 'forever':
        return None
    else:
        return now + timedelta(days=1)

# ========== КОМАНДЫ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
                  (user.id, user.username, user.first_name))
    conn.commit()
    conn.close()
    
    keyboard = [[InlineKeyboardButton("🗺️ Открыть карту", web_app=WebAppInfo(url=WEB_APP_URL))]]
    
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "📍 **КАК ВКЛЮЧИТЬ ГЕОЛОКАЦИЮ 24/7:**\n"
        "1. Открой чат со мной\n"
        "2. Нажми на скрепку 📎\n"
        "3. Выбери «Геопозиция»\n"
        "4. Нажми «Отметить как точку»\n"
        "5. Включи **«Пока не отключу»**\n\n"
        "✅ После этого я буду получать твои координаты каждые 10 секунд\n"
        "и напоминать о делах в нужных местах!\n\n"
        "👇 **Нажми кнопку, чтобы открыть карту**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем геолокацию от пользователя (каждые 5-10 секунд при трансляции)"""
    user = update.effective_user
    location = update.message.location
    
    print(f"📍 Получена геолокация от {user.id}: {location.latitude}, {location.longitude}")
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Обновляем время последней геолокации
    cursor.execute('''
        UPDATE users 
        SET last_lat = ?, last_lng = ?, last_location_update = ?
        WHERE user_id = ?
    ''', (location.latitude, location.longitude, datetime.now(), user.id))
    conn.commit()
    
    # Проверяем активные напоминания
    cursor.execute('''
        SELECT * FROM reminders 
        WHERE user_id = ? AND is_active = 1 
        AND (expires_at IS NULL OR expires_at > ?)
    ''', (user.id, datetime.now()))
    
    active_reminders = cursor.fetchall()
    
    for r in active_reminders:
        distance = haversine(location.latitude, location.longitude, r['lat'], r['lng'])
        
        if distance <= r['radius']:
            # Проверяем не отправляли ли недавно (для повторяющихся)
            if not r['last_triggered'] or \
               (datetime.now() - datetime.fromisoformat(r['last_triggered'])).seconds > 3600:
                
                cursor.execute('UPDATE reminders SET last_triggered = ? WHERE id = ?',
                             (datetime.now(), r['id']))
                
                # Для одноразовых - деактивируем
                if r['repeat_type'] == 'once':
                    cursor.execute('UPDATE reminders SET is_active = 0 WHERE id = ?', (r['id'],))
                
                conn.commit()
                
                await context.bot.send_message(
                    chat_id=user.id,
                    text=f"🔔 **НАПОМИНАНИЕ!**\n\n{r['text']}",
                    parse_mode='Markdown'
                )
                print(f"✅ Отправлено напоминание {r['id']}")
    
    conn.close()

async def check_location_loss(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет потерю геолокации (каждую минуту)"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Ищем пользователей с активными напоминаниями,
    # у которых геолокация старше 70 секунд
    cursor.execute('''
        SELECT DISTINCT u.user_id, u.first_name, u.last_location_update
        FROM users u
        JOIN reminders r ON u.user_id = r.user_id
        WHERE r.is_active = 1 
        AND (u.last_location_update IS NULL 
             OR u.last_location_update < datetime('now', '-70 seconds'))
    ''')
    
    lost_users = cursor.fetchall()
    conn.close()
    
    for user in lost_users:
        try:
            # Проверяем, не отправляли ли уже уведомление за последние 5 минут
            cache_key = f"location_warning_{user['user_id']}"
            if context.bot_data.get(cache_key):
                continue
            
            time_str = "никогда"
            if user['last_location_update']:
                last = datetime.fromisoformat(user['last_location_update'])
                minutes_ago = int((datetime.now() - last).total_seconds() / 60)
                time_str = f"{minutes_ago} минут назад"
            
            await context.bot.send_message(
                chat_id=user['user_id'],
                text="⚠️ **ГЕОЛОКАЦИЯ ПОТЕРЯНА!**\n\n"
                     f"Последние координаты были получены {time_str}.\n"
                     "У тебя есть активные напоминания, но я не вижу где ты.\n\n"
                     "📍 **ЧТО ДЕЛАТЬ:**\n"
                     "1. Открой чат со мной\n"
                     "2. Нажми на скрепку 📎 → Геопозиция\n"
                     "3. Выбери **«Пока не отключу»**\n\n"
                     "🔔 Как только геолокация появится, я продолжу следить!",
                parse_mode='Markdown'
            )
            
            # Ставим метку на 5 минут
            context.bot_data[cache_key] = True
            context.job_queue.run_once(
                lambda ctx: ctx.bot_data.pop(cache_key, None), 
                300
            )
            
            print(f"📨 Уведомление о потере гео отправлено {user['user_id']}")
        except Exception as e:
            print(f"❌ Ошибка уведомления: {e}")

async def check_expired_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Деактивирует истекшие напоминания"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE reminders SET is_active = 0 
        WHERE expires_at IS NOT NULL AND expires_at < ?
    ''', (datetime.now(),))
    
    affected = cursor.rowcount
    if affected > 0:
        print(f"🧹 Деактивировано {affected} истекших напоминаний")
    
    conn.commit()
    conn.close()

async def web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка данных из Web App"""
    data = update.effective_message.web_app_data
    if not data:
        return
    
    print(f"📦 Получено из Web App: {data.data}")
    
    try:
        payload = json.loads(data.data)
        user_id = update.effective_user.id
        action = payload.get('action')
        
        conn = get_db()
        cursor = conn.cursor()
        
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
            ''', (user_id, r.get('place_id'), r['text'], r['lat'], r['lng'], 
                  r.get('radius', 200), r.get('repeat', 'once'), datetime.now(), expires_at))
            conn.commit()
            await update.effective_message.reply_text(
                json.dumps({'type': 'success', 'message': '✅ Напоминание создано'})
            )
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        await update.effective_message.reply_text(
            json.dumps({'type': 'error', 'message': str(e)})
        )

# ========== ЗАПУСК ==========
def main():
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Хендлеры
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data))
    
    # Периодические задачи
    job_queue = app.job_queue
    if job_queue:
        # Проверка потери геолокации КАЖДУЮ МИНУТУ
        job_queue.run_repeating(check_location_loss, interval=60, first=30)
        
        # Проверка истекших напоминаний (раз в час)
        job_queue.run_repeating(check_expired_reminders, interval=3600, first=10)
        
        print("⏰ Планировщик задач запущен")
        print("📍 Проверка геолокации: каждые 60 секунд")
    
    print("🚀 Бот запущен!")
    print("📡 Режим: 24/7 отслеживание геолокации")
    print("⏱️ Потеря гео → уведомление через 70 секунд")
    app.run_polling()

if __name__ == "__main__":
    main()
