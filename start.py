import subprocess
import threading
import time
import os
import sys

def run_bot():
    """Запуск бота"""
    print("🤖 Запускаем бота...")
    subprocess.run([sys.executable, "bot.py"])

def run_server():
    """Запуск простого HTTP сервера для Web App"""
    print("🌐 Запускаем веб-сервер на порту 8000...")
    os.chdir(os.path.dirname(__file__))
    subprocess.run([sys.executable, "-m", "http.server", "8000"])

if __name__ == "__main__":
    print("🚀 Запускаем GeoReminder WebApp...")
    
    # Запускаем сервер для веб-приложения в отдельном потоке
    server_thread = threading.Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    
    time.sleep(2)  # Даем серверу время запуститься
    
    # Запускаем бота
    run_bot()