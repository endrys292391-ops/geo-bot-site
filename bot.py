import logging
import sqlite3
import math
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = "7618653140:AAFLWh4VFiKb3Ig6c0tQNyEi0byxdhC0Usk"
WEB_APP_URL = "https://geo-bot-site.onrender.com"

logging.basicConfig(format='%(asmtime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ ==========
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
            location_updated TIMESTAMP
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
            created_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
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
            next_trigger TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (place_id) REFERENCES favorite_places(id)
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

def calculate_next_trigger(repeat_type):
    """Вычисляет следующее время срабатывания"""
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
        return now  # Сработало и готово к удалению

# ========== КОМАНДЫ БОТА ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню с Web App"""
    user = update.effective_user
    
    # Сохраняем пользователя
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
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
    
    # Добавляем инструкцию по геолокации
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "📍 **Как включить геолокацию в фоне:**\n\n"
        "**Android:**\n"
        "1. Настройки Telegram → Конфиденциальность → Геопозиция\n"
        "2. Разрешить доступ «Всегда»\n\n"
        "**iPhone:**\n"
        "1. Настройки телефона → Telegram → Геопозиция\n"
        "2. Выбрать «Всегда»\n\n"
        "После этого я смогу напоминать тебе о делах, даже когда Telegram закрыт!\n\n"
        "👇 Нажми кнопку ниже, чтобы открыть карту",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка данных из Web App"""
    data = update.effective_message.web_app_data
    if not data:
        return
    
    try:
        payload = json.loads(data.data)
        user_id = update.effective_user.id
        action = payload.get('action')
        
        print(f"📦 Получено действие: {action} от {user_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # ===== ИЗБРАННЫЕ МЕСТА =====
        if action == 'get_places':
            cursor.execute('''
                SELECT * FROM favorite_places 
                WHERE user_id = ? 
                ORDER BY created_at DESC
            ''', (user_id,))
            places = cursor.fetchall()
            
            # Отправляем обратно в Web App
            await update.effective_message.reply_text(
                json.dumps({
                    'type': 'places',
                    'places': [dict(p) for p in places]
                }, default=str)
            )
            print(f"✅ Отправлено {len(places)} мест")
        
        elif action == 'add_place':
            place = payload['place']
            cursor.execute('''
                INSERT INTO favorite_places (user_id, name, address, lat, lng, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, place['name'], place['address'], place['lat'], place['lng'], datetime.now()))
            conn.commit()
            print(f"✅ Место добавлено: {place['name']}")
            
            # Подтверждение
            await update.effective_message.reply_text(
                json.dumps({'type': 'success', 'message': 'Место сохранено'})
            )
        
        elif action == 'delete_place':
            place_id = payload['place_id']
            cursor.execute('DELETE FROM favorite_places WHERE id = ? AND user_id = ?', (place_id, user_id))
            conn.commit()
            print(f"✅ Место {place_id} удалено")
            
            await update.effective_message.reply_text(
                json.dumps({'type': 'success', 'message': 'Место удалено'})
            )
        
        # ===== НАПОМИНАНИЯ =====
        elif action == 'get_reminders':
            cursor.execute('''
                SELECT r.*, fp.name as place_name, fp.address as place_address
                FROM reminders r
                LEFT JOIN favorite_places fp ON r.place_id = fp.id
                WHERE r.user_id = ? AND r.is_active = 1
                ORDER BY r.created_at DESC
            ''', (user_id,))
            reminders = cursor.fetchall()
            
            await update.effective_message.reply_text(
                json.dumps({
                    'type': 'reminders',
                    'reminders': [dict(r) for r in reminders]
                }, default=str)
            )
            print(f"✅ Отправлено {len(reminders)} напоминаний")
        
        elif action == 'add_reminder':
            reminder = payload['reminder']
            
            # Определяем следующий запуск
            next_trigger = calculate_next_trigger(reminder.get('repeat', 'once'))
            
            cursor.execute('''
                INSERT INTO reminders 
                (user_id, place_id, text, lat, lng, radius, repeat_type, created_at, next_trigger)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, 
                reminder.get('place_id'), 
                reminder['text'], 
                reminder['lat'], 
                reminder['lng'], 
                reminder.get('radius', 200),
                reminder.get('repeat', 'once'),
                datetime.now(),
                next_trigger
            ))
            conn.commit()
            print(f"✅ Напоминание создано: {reminder['text']}")
            
            await update.effective_message.reply_text(
                json.dumps({'type': 'success', 'message': 'Напоминание создано'})
            )
        
        # ===== ПРОВЕРКА ГЕОЛОКАЦИИ =====
        elif action == 'check_location':
            lat = payload['lat']
            lng = payload['lng']
            
            # Обновляем последнюю позицию пользователя
            cursor.execute('''
                UPDATE users SET last_lat = ?, last_lng = ?, location_updated = ?
                WHERE user_id = ?
            ''', (lat, lng, datetime.now(), user_id))
            conn.commit()
            
            # Проверяем активные напоминания
            cursor.execute('''
                SELECT * FROM reminders 
                WHERE user_id = ? AND is_active = 1 
                AND (next_trigger IS NULL OR next_trigger <= ?)
            ''', (user_id, datetime.now()))
            
            active_reminders = cursor.fetchall()
            triggered = []
            
            for r in active_reminders:
                distance = haversine(lat, lng, r['lat'], r['lng'])
                
                if distance <= r['radius']:
                    # Проверяем не отправляли ли недавно
                    if not r['last_triggered'] or \
                       (datetime.now() - datetime.fromisoformat(r['last_triggered'])).seconds > 3600:
                        
                        # Обновляем last_triggered
                        cursor.execute('''
                            UPDATE reminders SET last_triggered = ? WHERE id = ?
                        ''', (datetime.now(), r['id']))
                        
                        # Вычисляем следующий запуск
                        next_trigger = calculate_next_trigger(r['repeat_type'])
                        
                        if next_trigger and r['repeat_type'] != 'once':
                            # Если повторяющееся - обновляем next_trigger
                            cursor.execute('''
                                UPDATE reminders SET next_trigger = ? WHERE id = ?
                            ''', (next_trigger, r['id']))
                        elif r['repeat_type'] == 'once':
                            # Если одноразовое - деактивируем
                            cursor.execute('''
                                UPDATE reminders SET is_active = 0 WHERE id = ?
                            ''', (r['id'],))
                        
                        conn.commit()
                        
                        # Отправляем уведомление
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"🔔 **Напоминание!**\n\n{r['text']}",
                            parse_mode='Markdown'
                        )
                        triggered.append(r['id'])
                        print(f"✅ Отправлено напоминание {r['id']}")
            
            print(f"📊 Проверено {len(active_reminders)} напоминаний, отправлено {len(triggered)}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        logger.error(f"Ошибка: {e}")
        await update.effective_message.reply_text(
            json.dumps({'type': 'error', 'message': 'Произошла ошибка'})
        )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текста"""
    await update.message.reply_text("Используй /start для открытия меню")

def main():
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🚀 Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
