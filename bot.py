import logging
import sqlite3
import math
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

BOT_TOKEN = "7618653140:AAFLWh4VFiKb3Ig6c0tQNyEi0byxdhC0Usk"  # Твой токен
WEB_APP_URL = "https://476133794eadd512-37-214-70-139.serveousercontent.com"  # URL где будет твое веб-приложение

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
            first_name TEXT
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
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP,
            last_triggered TIMESTAMP
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

# ========== КОМАНДЫ БОТА ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открываем Web App"""
    user = update.effective_user
    print(f"🔥 START от пользователя {user.id} - {user.first_name}")
    
    # Сохраняем пользователя
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
        ''', (user.id, user.username, user.first_name))
        conn.commit()
        conn.close()
        print(f"✅ Пользователь {user.id} сохранен в БД")
    except Exception as e:
        print(f"❌ Ошибка сохранения пользователя: {e}")
    
    # Кнопка для открытия Web App
    keyboard = [[
        InlineKeyboardButton(
            "🗺️ Открыть карту и избранное",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )
    ]]
    
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "Нажми кнопку ниже, чтобы открыть карту и управлять напоминаниями!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    print(f"✅ Ответ на start отправлен пользователю {user.id}")

async def web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем данные из Web App"""
    print("📦 Получены данные из Web App")
    data = update.effective_message.web_app_data
    if not data:
        print("❌ Нет данных")
        return
    
    try:
        payload = json.loads(data.data)
        user_id = update.effective_user.id
        action = payload.get('action')
        print(f"📦 Действие: {action} от пользователя {user_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        if action == 'get_places':
            print(f"📦 Запрос списка мест для пользователя {user_id}")
            cursor.execute('SELECT * FROM favorite_places WHERE user_id = ?', (user_id,))
            places = cursor.fetchall()
            places_list = [dict(p) for p in places]
            print(f"📦 Найдено мест: {len(places_list)}")
            # Отправляем через callback query или сообщение
            await update.message.reply_text(json.dumps(places_list, default=str))
        
        elif action == 'add_place':
            print(f"📦 Добавление нового места")
            place = payload['place']
            cursor.execute('''
                INSERT INTO favorite_places (user_id, name, address, lat, lng, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, place['name'], place['address'], place['lat'], place['lng'], datetime.now()))
            conn.commit()
            print(f"✅ Место добавлено в БД")
            await update.message.reply_text("✅ Место добавлено в избранное")
        
        elif action == 'delete_place':
            print(f"📦 Удаление места")
            place_id = payload['place_id']
            cursor.execute('DELETE FROM favorite_places WHERE id = ? AND user_id = ?', (place_id, user_id))
            conn.commit()
            print(f"✅ Место удалено из БД")
            await update.message.reply_text("✅ Место удалено")
        
        elif action == 'add_reminder':
            print(f"📦 Добавление напоминания")
            reminder = payload['reminder']
            cursor.execute('''
                INSERT INTO reminders (user_id, place_id, text, lat, lng, radius, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, reminder.get('place_id'), reminder['text'], 
                  reminder['lat'], reminder['lng'], reminder.get('radius', 200), datetime.now()))
            conn.commit()
            print(f"✅ Напоминание добавлено в БД")
            await update.message.reply_text("✅ Напоминание создано")
        
        elif action == 'check_location':
            print(f"📦 Проверка локации")
            lat = payload['lat']
            lng = payload['lng']
            
            cursor.execute('SELECT * FROM reminders WHERE user_id = ? AND is_active = 1', (user_id,))
            reminders = cursor.fetchall()
            print(f"📦 Активных напоминаний: {len(reminders)}")
            
            for r in reminders:
                distance = haversine(lat, lng, r['lat'], r['lng'])
                print(f"📦 Расстояние до напоминания {r['id']}: {distance}м")
                
                if distance <= r['radius']:
                    # Проверяем не отправляли ли недавно
                    if not r['last_triggered'] or \
                       (datetime.now() - datetime.fromisoformat(r['last_triggered'])).seconds > 3600:
                        
                        cursor.execute('UPDATE reminders SET last_triggered = ? WHERE id = ?', 
                                     (datetime.now(), r['id']))
                        conn.commit()
                        
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"🔔 Напоминание!\n{r['text']}"
                        )
                        print(f"✅ Напоминание {r['id']} отправлено")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("❌ Произошла ошибка")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    print(f"📝 Текстовое сообщение от {update.effective_user.id}: {update.message.text}")
    await update.message.reply_text("Используй /start для открытия меню")

def main():
    print("🚀 Запуск бота...")
    print(f"🔑 Токен: {BOT_TOKEN[:10]}...")
    print(f"🌐 Web App URL: {WEB_APP_URL}")
    
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    print("✅ Application создан")
    
    # Хендлеры
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("✅ Хендлеры добавлены")
    print("🤖 Бот запущен! Нажми Ctrl+C для остановки")
    
    app.run_polling()

if __name__ == "__main__":
    main()