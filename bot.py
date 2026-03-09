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
            repeat_type TEXT DEFAULT 'once',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP,
            last_triggered TIMESTAMP,
            next_trigger TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ База данных готова")

init_db()

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
        "📍 **Геолокация в фоне:**\n"
        "Android: Настройки Telegram → Конфиденциальность → Геопозиция → Всегда\n"
        "iPhone: Настройки → Telegram → Геопозиция → Всегда\n\n"
        "👇 Нажми кнопку",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        
        if action == 'get_places':
            cursor.execute('SELECT * FROM favorite_places WHERE user_id = ?', (user_id,))
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
            cursor.execute('SELECT * FROM reminders WHERE user_id = ? AND is_active = 1', (user_id,))
            reminders = cursor.fetchall()
            await update.effective_message.reply_text(
                json.dumps({'type': 'reminders', 'reminders': [dict(r) for r in reminders]}, default=str)
            )
        
        elif action == 'add_reminder':
            r = payload['reminder']
            cursor.execute('''
                INSERT INTO reminders (user_id, place_id, text, lat, lng, radius, repeat_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, r.get('place_id'), r['text'], r['lat'], r['lng'], r['radius'], r['repeat'], datetime.now()))
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

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data))
    print("🚀 Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
