import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import openai
from config import BOT_TOKEN, OPENAI_API_KEY, ADMIN_IDS, CRYPTO_CURRENCIES, QUOTE_CURRENCIES
import threading
import time

bot = telebot.TeleBot(BOT_TOKEN)
openai.api_key = OPENAI_API_KEY

# Хранилище настроек уведомлений для админов: {admin_id: {"BTC": True/False, ...}}
notify_settings = {admin_id: {crypto: False for crypto in CRYPTO_CURRENCIES} for admin_id in ADMIN_IDS}

# Последние цены для отслеживания изменений
last_prices = {admin_id: {} for admin_id in ADMIN_IDS}

def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_crypto_price(crypto, vs_currency="usd"):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={crypto}&vs_currencies={vs_currency}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if crypto in data and vs_currency in data[crypto]:
            return data[crypto][vs_currency]
    except:
        pass
    return None

def get_crypto_id(ticker):
    mapping = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
    return mapping.get(ticker.upper())

def analyze_with_ai(crypto, price_usd, price_rub):
    prompt = f"""
Криптовалюта: {crypto}
Цена сейчас: {price_usd} USD, {price_rub} RUB.
Проанализируй краткосрочный тренд (ближайшие 1-4 часа). Куда пойдет график: вверх, вниз или флет? Дай краткий ответ (1-2 предложения) без лишнего текста.
"""
    try:
        # Исправленный способ инициализации клиента для новых версий openai
        client = openai.OpenAI(
            api_key=OPENAI_API_KEY,
            base_url="https://api.openai.com/v1"
        )
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Ошибка AI: {str(e)}"

def send_analysis(chat_id, crypto):
    crypto_id = get_crypto_id(crypto)
    if not crypto_id:
        bot.send_message(chat_id, f"Валюта {crypto} не найдена")
        return
    
    price_usd = get_crypto_price(crypto_id, "usd")
    price_rub = get_crypto_price(crypto_id, "rub")
    
    if price_usd is None:
        bot.send_message(chat_id, f"Не удалось получить цену {crypto}")
        return
    
    price_rub = price_rub if price_rub else price_usd * 90  # fallback
    
    bot.send_message(chat_id, f"Получаю анализ для {crypto}...")
    analysis = analyze_with_ai(crypto, price_usd, price_rub)
    
    message = f"""
{crypto}:
Цена: {price_usd} USD
Цена: {price_rub} RUB
Анализ AI: {analysis}
"""
    bot.send_message(chat_id, message.strip())

def monitor_prices():
    while True:
        for admin_id in ADMIN_IDS:
            for crypto in CRYPTO_CURRENCIES:
                if notify_settings[admin_id].get(crypto, False):
                    crypto_id = get_crypto_id(crypto)
                    if crypto_id:
                        price_usd = get_crypto_price(crypto_id, "usd")
                        if price_usd is not None:
                            last = last_prices[admin_id].get(crypto)
                            if last is not None:
                                change = ((price_usd - last) / last) * 100
                                if abs(change) >= 0.5:  # 0.5% порог
                                    direction = "выросла" if change > 0 else "упала"
                                    bot.send_message(
                                        admin_id,
                                        f"{crypto} цена {direction} на {abs(change):.2f}%: {price_usd} USD"
                                    )
                            last_prices[admin_id][crypto] = price_usd
        time.sleep(60)  # проверка каждую минуту

@bot.message_handler(commands=['start'])
def start_command(message):
    if not is_admin(message.chat.id):
        bot.send_message(message.chat.id, "Вы не админ и не сможете взаимодействовать с ботом")
        return
    
    markup = InlineKeyboardMarkup()
    for crypto in CRYPTO_CURRENCIES:
        markup.add(InlineKeyboardButton(crypto, callback_data=f"analyze_{crypto}"))
    bot.send_message(message.chat.id, "Выберите валюту для анализа:", reply_markup=markup)

@bot.message_handler(commands=['settings'])
def settings_command(message):
    if not is_admin(message.chat.id):
        bot.send_message(message.chat.id, "Вы не админ и не сможете взаимодействовать с ботом")
        return
    
    admin_id = message.chat.id
    markup = InlineKeyboardMarkup()
    for crypto in CRYPTO_CURRENCIES:
        status = "Вкл" if notify_settings[admin_id].get(crypto, False) else "Выкл"
        markup.add(InlineKeyboardButton(f"{crypto} уведомления: {status}", callback_data=f"toggle_{crypto}"))
    bot.send_message(message.chat.id, "Настройки уведомлений об изменении цены:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    admin_id = call.message.chat.id
    if not is_admin(admin_id):
        bot.answer_callback_query(call.id, "Нет доступа")
        return
    
    if call.data.startswith("analyze_"):
        crypto = call.data.split("_")[1]
        bot.answer_callback_query(call.id)
        threading.Thread(target=send_analysis, args=(admin_id, crypto)).start()
    
    elif call.data.startswith("toggle_"):
        crypto = call.data.split("_")[1]
        current = notify_settings[admin_id].get(crypto, False)
        notify_settings[admin_id][crypto] = not current
        status = "включены" if notify_settings[admin_id][crypto] else "выключены"
        bot.answer_callback_query(call.id, f"Уведомления для {crypto} {status}")
        
        # обновляем клавиатуру
        markup = InlineKeyboardMarkup()
        for c in CRYPTO_CURRENCIES:
            st = "Вкл" if notify_settings[admin_id].get(c, False) else "Выкл"
            markup.add(InlineKeyboardButton(f"{c} уведомления: {st}", callback_data=f"toggle_{c}"))
        bot.edit_message_text("Настройки уведомлений об изменении цены:", admin_id, call.message.message_id, reply_markup=markup)

if __name__ == "__main__":
    # Запускаем мониторинг цен в фоне
    monitor_thread = threading.Thread(target=monitor_prices, daemon=True)
    monitor_thread.start()
    
    print("Бот запущен")
    bot.infinity_polling()
