import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import pandas as pd
import numpy as np
import openai
from config import BOT_TOKEN, OPENAI_API_KEY, ADMIN_IDS, CRYPTO_CURRENCIES
import threading
import time
from datetime import datetime

bot = telebot.TeleBot(BOT_TOKEN)
openai.api_key = OPENAI_API_KEY

notify_settings = {admin_id: {crypto: False for crypto in CRYPTO_CURRENCIES} for admin_id in ADMIN_IDS}
last_prices = {admin_id: {} for admin_id in ADMIN_IDS}

def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_klines_from_bybit(symbol, interval="15", limit=100):
    """Получает свечные данные с Bybit через прямой HTTP запрос"""
    try:
        # Bybit v5 API
        url = "https://api.bybit.com/v5/market/kline"
        params = {
            "category": "spot",
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data["retCode"] == 0:
            klines = data["result"]["list"]
            # Преобразуем в DataFrame
            df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
            df['close'] = df['close'].astype(float)
            df['open'] = df['open'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['volume'] = df['volume'].astype(float)
            df['timestamp'] = pd.to_datetime(df['timestamp'].astype(int), unit='ms')
            return df
    except Exception as e:
        print(f"Bybit ошибка: {e}")
    return None

def calculate_indicators(df):
    """Рассчитывает технические индикаторы"""
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['signal']
    
    # Скользящие средние
    df['ma20'] = df['close'].rolling(window=20).mean()
    df['ma50'] = df['close'].rolling(window=50).mean()
    
    return df

def analyze_with_ai_and_indicators(symbol, df):
    """Анализирует рынок используя реальные индикаторы + AI"""
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    current_price = last['close']
    prev_price = prev['close']
    price_change = ((current_price - prev_price) / prev_price) * 100
    
    rsi = last['rsi'] if not pd.isna(last['rsi']) else 50
    macd_hist = last['macd_hist'] if not pd.isna(last['macd_hist']) else 0
    ma20 = last['ma20'] if not pd.isna(last['ma20']) else current_price
    ma50 = last['ma50'] if not pd.isna(last['ma50']) else current_price
    
    # Определяем тренд по индикаторам
    trend_signals = []
    
    if rsi > 70:
        trend_signals.append("RSI показывает перекупленность (сигнал к снижению)")
    elif rsi < 30:
        trend_signals.append("RSI показывает перепроданность (сигнал к росту)")
    else:
        trend_signals.append(f"RSI нейтральный ({rsi:.1f})")
    
    if macd_hist > 0:
        trend_signals.append("MACD гистограмма положительная (бычий импульс)")
    elif macd_hist < 0:
        trend_signals.append("MACD гистограмма отрицательная (медвежий импульс)")
    
    if current_price > ma20 and current_price > ma50:
        trend_signals.append("Цена выше MA20 и MA50 (восходящий тренд)")
    elif current_price < ma20 and current_price < ma50:
        trend_signals.append("Цена ниже MA20 и MA50 (нисходящий тренд)")
    else:
        trend_signals.append("Цена около скользящих средних (неопределенность)")
    
    # Формируем прогноз
    bullish_score = 0
    if rsi < 40:
        bullish_score += 1
    if macd_hist > 0:
        bullish_score += 1
    if current_price > ma20:
        bullish_score += 1
    if price_change > 0:
        bullish_score += 0.5
    
    if bullish_score >= 2.5:
        prediction = "вверх"
        confidence = "высокая"
    elif bullish_score <= 1:
        prediction = "вниз"
        confidence = "высокая"
    else:
        prediction = "флет"
        confidence = "средняя"
    
    # Отправляем данные в AI
    prompt = f"""
Криптовалюта: {symbol}
Текущая цена: {current_price} USDT
Изменение за последнюю свечу: {price_change:.2f}%

Технические индикаторы:
{'; '.join(trend_signals)}

На основе этих реальных данных с биржи Bybit, куда вероятнее всего пойдет график в ближайшие 1-4 часа: вверх, вниз или флет?
Ответь кратко (1-2 предложения) с обоснованием.
"""
    
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.5
        )
        ai_analysis = response.choices[0].message.content.strip()
    except Exception as e:
        ai_analysis = f"Ошибка AI: {e}"
    
    result = f"""
{symbol} - АНАЛИЗ РЫНКА (Bybit)

Текущая цена: {current_price} USDT
Изменение: {price_change:+.2f}%

ИНДИКАТОРЫ:
RSI (14): {rsi:.1f}
MACD: {'бычий' if macd_hist > 0 else 'медвежий'}
MA20: {ma20:.2f}
MA50: {ma50:.2f}

ПРОГНОЗ: {prediction.upper()} ({confidence} уверенность)

AI АНАЛИЗ:
{ai_analysis}

Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    return result, current_price

def send_analysis(chat_id, crypto_symbol):
    message = bot.send_message(chat_id, f"Загружаю данные с Bybit для {crypto_symbol}...")
    
    df = get_klines_from_bybit(crypto_symbol, interval="15", limit=100)
    
    if df is None or len(df) < 50:
        bot.edit_message_text(f"Ошибка: не удалось получить данные с Bybit для {crypto_symbol}", chat_id, message.message_id)
        return
    
    df = calculate_indicators(df)
    analysis, price = analyze_with_ai_and_indicators(crypto_symbol, df)
    
    bot.edit_message_text(analysis, chat_id, message.message_id)
    
    for admin_id in ADMIN_IDS:
        last_prices[admin_id][crypto_symbol] = price

def monitor_prices():
    while True:
        for admin_id in ADMIN_IDS:
            for crypto in CRYPTO_CURRENCIES:
                if notify_settings[admin_id].get(crypto, False):
                    df = get_klines_from_bybit(crypto, interval="5", limit=5)
                    if df is not None and len(df) > 0:
                        current_price = df.iloc[-1]['close']
                        last = last_prices[admin_id].get(crypto)
                        if last is not None:
                            change = ((current_price - last) / last) * 100
                            if abs(change) >= 0.5:
                                direction = "выросла" if change > 0 else "упала"
                                bot.send_message(
                                    admin_id,
                                    f"{crypto} цена {direction} на {abs(change):.2f}%: {current_price} USDT"
                                )
                        last_prices[admin_id][crypto] = current_price
        time.sleep(60)

@bot.message_handler(commands=['start'])
def start_command(message):
    if not is_admin(message.chat.id):
        bot.send_message(message.chat.id, "Вы не админ и не сможете взаимодействовать с ботом")
        return
    
    markup = InlineKeyboardMarkup()
    for crypto in CRYPTO_CURRENCIES:
        markup.add(InlineKeyboardButton(crypto, callback_data=f"analyze_{crypto}"))
    bot.send_message(message.chat.id, "Выберите валюту для анализа (данные с Bybit):", reply_markup=markup)

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
        
        markup = InlineKeyboardMarkup()
        for c in CRYPTO_CURRENCIES:
            st = "Вкл" if notify_settings[admin_id].get(c, False) else "Выкл"
            markup.add(InlineKeyboardButton(f"{c} уведомления: {st}", callback_data=f"toggle_{c}"))
        bot.edit_message_text("Настройки уведомлений об изменении цены:", admin_id, call.message.message_id, reply_markup=markup)

if __name__ == "__main__":
    monitor_thread = threading.Thread(target=monitor_prices, daemon=True)
    monitor_thread.start()
    
    print("Бот запущен. Данные берутся с Bybit через HTTP API")
    bot.infinity_polling()
