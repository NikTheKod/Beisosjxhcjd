import os
from dotenv import load_dotenv

load_dotenv()

# Токен бота от BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN")

# API ключ OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ID админов (через запятую в .env, например: 123456789,987654321)
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))

# Какие криптовалюты нужны (тикеры)
CRYPTO_CURRENCIES = ["BTC", "ETH", "SOL"]

# Валюты котировок
QUOTE_CURRENCIES = ["USD", "RUB"]
