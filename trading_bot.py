import time
import krakenex
from pykrakenapi import KrakenAPI
import pandas as pd
from telegram.ext import Updater, CommandHandler
from config import KRAKEN_API_KEY, KRAKEN_API_SECRET, TELEGRAM_BOT_TOKEN
from datetime import datetime

# Kraken API setup
kraken = krakenex.API(key=KRAKEN_API_KEY, secret=KRAKEN_API_SECRET)
api = KrakenAPI(kraken)

# Trading parameters
SYMBOL = 'ETHUSD'
TRADE_AMOUNT = 0.01  # Amount of ETH to buy/sell per trade
STOP_LOSS_PERCENTAGE = 0.05  # Stop loss at 5% below the buy price
TAKE_PROFIT_PERCENTAGE = 0.10  # Take profit at 10% above the buy price
TRADE_HISTORY_FILE = "trade_history.csv"

# Initialize trade history logging
def log_trade(action, price, amount):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    trade = {'timestamp': timestamp, 'action': action, 'price': price, 'amount': amount}
    
    try:
        df = pd.read_csv(TRADE_HISTORY_FILE)
    except FileNotFoundError:
        df = pd.DataFrame(columns=['timestamp', 'action', 'price', 'amount'])
    
    df = df.append(trade, ignore_index=True)
    df.to_csv(TRADE_HISTORY_FILE, index=False)

# Function to fetch the latest price data from Kraken
def get_price_data(pair, interval, lookback):
    ohlc, _ = api.get_ohlc_data(pair, interval=interval, ascending=True)
    return ohlc.tail(lookback)

# RSI Calculation
def calculate_rsi(df, periods=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=periods).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=periods).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# Bollinger Bands Calculation
def calculate_bollinger_bands(df, window=20, std_factor=2):
    df['middle_band'] = df['close'].rolling(window=window).mean()
    df['std'] = df['close'].rolling(window=window).std()
    df['upper_band'] = df['middle_band'] + std_factor * df['std']
    df['lower_band'] = df['middle_band'] - std_factor * df['std']
    return df[['upper_band', 'middle_band', 'lower_band']]

# Advanced Trading Strategy with MA, RSI, and Bollinger Bands
def advanced_trading_strategy(symbol='ETHUSD', short_ma_window=9, long_ma_window=21, rsi_threshold=30):
    df = get_price_data(symbol, 60, 100)  # 1-hour data, 100 candles
    df['short_ma'] = df['close'].rolling(window=short_ma_window).mean()
    df['long_ma'] = df['close'].rolling(window=long_ma_window).mean()
    df['rsi'] = calculate_rsi(df)
    df[['upper_band', 'middle_band', 'lower_band']] = calculate_bollinger_bands(df)

    # Buy Signal
    if (
        df['short_ma'].iloc[-2] < df['long_ma'].iloc[-2] and df['short_ma'].iloc[-1] > df['long_ma'].iloc[-1]  # Moving average crossover
        and df['rsi'].iloc[-1] < rsi_threshold  # RSI underbought
        and df['close'].iloc[-1] < df['lower_band'].iloc[-1]  # Price near lower Bollinger Band
    ):
        return 'buy', df['close'].iloc[-1]
    
    # Sell Signal
    elif (
        df['short_ma'].iloc[-2] > df['long_ma'].iloc[-2] and df['short_ma'].iloc[-1] < df['long_ma'].iloc[-1]  # Moving average crossover
        and df['rsi'].iloc[-1] > (100 - rsi_threshold)  # RSI overbought
        and df['close'].iloc[-1] > df['upper_band'].iloc[-1]  # Price near upper Boll        and df['close'].iloc[-1] > df['upper_band'].iloc[-1]  # Price near upper Bollinger Band
    ):
        return 'sell', df['close'].iloc[-1]
    
    return None, None

# Place Kraken order
def place_order(order_type, symbol, quantity):
    if order_type == 'buy':
        order = kraken.query_private('AddOrder', {'pair': symbol, 'type': 'buy', 'ordertype': 'market', 'volume': quantity})
    elif order_type == 'sell':
        order = kraken.query_private('AddOrder', {'pair': symbol, 'type': 'sell', 'ordertype': 'market', 'volume': quantity})
    return order

# Stop-Loss and Take-Profit Management
def manage_trades(entry_price, current_price):
    stop_loss_price = entry_price * (1 - STOP_LOSS_PERCENTAGE)
    take_profit_price = entry_price * (1 + TAKE_PROFIT_PERCENTAGE)
    
    if current_price <= stop_loss_price:
        return 'sell', f"Stop-loss triggered at {stop_loss_price} (current price: {current_price})"
    elif current_price >= take_profit_price:
        return 'sell', f"Take-profit triggered at {take_profit_price} (current price: {current_price})"
    
    return None, None

# Execute auto trade based on strategy and risk management
def auto_trade():
    signal, entry_price = advanced_trading_strategy(SYMBOL)
    
    if signal == 'buy':
        order = place_order('buy', SYMBOL, TRADE_AMOUNT)
        current_price = entry_price
        log_trade('buy', entry_price, TRADE_AMOUNT)
        trade_status = f"BUY executed at {entry_price}. Monitoring for stop-loss and take-profit."
        
        while True:
            current_price = get_price_data(SYMBOL, 60, 1)['close'].iloc[-1]
            action, message = manage_trades(entry_price, current_price)
            
            if action == 'sell':
                place_order('sell', SYMBOL, TRADE_AMOUNT)
                log_trade('sell', current_price, TRADE_AMOUNT)
                trade_status += f"\n{message}. SELL executed."
                break
            
            time.sleep(60)  # Check every minute
        return trade_status
    
    elif signal == 'sell':
        order = place_order('sell', SYMBOL, TRADE_AMOUNT)
        log_trade('sell', entry_price, TRADE_AMOUNT)
        return f"SELL executed at {entry_price}."
    
    return "No trade executed."

# Telegram Command Handlers
def start(update, context):
    """Send a message when the command /start is issued."""
    update.message.reply_text('Welcome! This bot trades ETH based on advanced trading strategies with stop-loss and take-profit.')

def trade(update, context):
    """Start auto trading."""
    result = auto_trade()
    update.message.reply_text(result)

def balance(update, context):
    """Check balance on Kraken when /balance is issued."""
    eth_balance = kraken.query_private('Balance')['result']['XETH']
    update.message.reply_text(f"Your ETH balance: {eth_balance} ETH")

def trade_history(update, context):
    """Send trade history to the user."""
    try:
        df = pd.read_csv(TRADE_HISTORY_FILE)
        history_message = df.to_string(index=False)
    except FileNotFoundError:
        history_message = "No trade history found."
    
    update.message.reply_text(history_message)

# Main function to set up the Telegram bot
def main():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("trade", trade))
    dp.add_handler(CommandHandler("balance", balance))
    dp.add_handler(CommandHandler("history", trade_history))

    # Start the bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()