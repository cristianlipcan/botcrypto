import os
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import logging
from datetime import datetime, timezone
from telegram import Bot

# ------- CONFIG -------
CONFIG = {
    "exchange": "binance",
    "symbols": [],  
    "timeframe_main": "15m",  
    "timeframe_confirm": "5m",  
    "limit": 200,
    "poll_interval": 30,
    "telegram_token": "7985772555:AAFxwAVWDmnihM_BZPpI8b8vso6bdS1jwCI",
    "telegram_chat_id": os.environ.get("1024585490"),
    "expiry_suggestion_seconds": 300,
    "top_symbols_count": 20,  
    "max_concurrent_requests": 5,  
    "min_signal_confidence": 60,  
}
# -----------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
bot = Bot(token=CONFIG["telegram_token"])

async def load_symbols(exchange):
    logging.info("Incarcare market data de la exchange...")
    markets = await exchange.load_markets()
    usdt_pairs = []
    for symbol, data in markets.items():
        if not isinstance(symbol, str):
            continue
        if symbol.endswith("/USDT") and data.get("active", True):
            try:
                vol = data.get("info", {}).get("quoteVolume") or data.get("quoteVolume") or 0
                vol = float(vol)
            except Exception:
                vol = 0
            usdt_pairs.append((symbol, vol))
    usdt_pairs.sort(key=lambda x: x[1], reverse=True)
    top_pairs = [sym for sym, vol in usdt_pairs[:CONFIG["top_symbols_count"]]]
    logging.info("Top %d perechi USDT dupa volum: %s", CONFIG["top_symbols_count"], top_pairs)
    return top_pairs

async def fetch_ohlcv(exchange, symbol, timeframe, limit):
    try:
        data = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not data:
            return None
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df
    except Exception as e:
        logging.exception("Eroare fetch_ohlcv pentru %s: %s", symbol, e)
        return None

def detect_break_and_retest(df, lookback=40, retest_tol=0.003):
    closes = df["close"]
    n = len(closes)
    if n < 10:
        return []
    recent = df[-lookback:]
    half = int(len(recent) / 2)
    if half <= 0:
        return []
    resistance = recent["high"].iloc[:half].max()
    breakout_zone = recent["close"].iloc[half:]
    breakout_idx = breakout_zone[breakout_zone > resistance].index
    if len(breakout_idx) == 0:
        return []
    br_time = breakout_idx[0]
    br_price = recent.loc[br_time, "close"]
    after_br = df.loc[br_time:]
    for t, row in after_br.iterrows():
        if resistance == 0:
            continue
        if abs(row["low"] - resistance) / resistance <= retest_tol:
            direction = "LONG" if br_price > resistance else "SHORT"
            return [{
                "pattern": "break_and_retest",
                "resistance": float(resistance),
                "break_price": float(br_price),
                "retest_time": str(t),
                "direction": direction
            }]
    return []

def score_signal(main_df, confirm_df, pattern_info):
    score = 0
    weights = {"distance": 50, "volume": 50}

    resistance = pattern_info.get("resistance") or pattern_info.get("break_price")
    if resistance:
        last_close = confirm_df["close"].iloc[-1]
        dist = abs(last_close - resistance) / resistance
        if dist <= 0.003:
            score += weights["distance"]
    vol_avg = confirm_df["volume"].rolling(20).mean().iloc[-1]
    vol_last = confirm_df["volume"].iloc[-1]
    if vol_avg and vol_last:
        if vol_last >= vol_avg * 1.2:
            score += weights["volume"]
    return round(score, 1)

async def send_telegram_message(chat_id, text):
    try:
        await bot.send_message(chat_id=chat_id, text=text)
        logging.info("Mesaj trimis Telegram.")
    except Exception as e:
        logging.exception("Eroare la trimiterea Telegram: %s", e)

async def analyze_symbol(exch, symbol, sent_signals, semaphore):
    async with semaphore:
        try:
            main_df = await fetch_ohlcv(exch, symbol, CONFIG["timeframe_main"], CONFIG["limit"])
            if main_df is None or main_df.empty:
                return
            confirm_df = await fetch_ohlcv(exch, symbol, CONFIG["timeframe_confirm"], CONFIG["limit"])
            if confirm_df is None or confirm_df.empty:
                return
            patterns = detect_break_and_retest(confirm_df)
            if not patterns:
                return
            for pattern in patterns:
                score = score_signal(main_df, confirm_df, pattern)
                if score >= CONFIG["min_signal_confidence"]:
                    key = f"{symbol}_{pattern['retest_time']}_{pattern['direction']}"
                    if key not in sent_signals:
                        msg = (
                            f"✅ Semnal {pattern['direction']} ({score}%) – {symbol}\n"
                            f"Break & Retest confirmat pe {CONFIG['timeframe_confirm']}/{CONFIG['timeframe_main']}\n"
                            f"Preț: {confirm_df['close'].iloc[-1]:.2f}\n"
                            f"Retest la: {pattern['retest_time']}\n"
                            f"Trimis: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                        )
                        await send_telegram_message(CONFIG["telegram_chat_id"], msg)
                        sent_signals.add(key)
        except Exception as e:
            logging.exception("[%s] Eroare in analiza simbol: %s", symbol, e)

async def main():
    exchange = getattr(ccxt, CONFIG["exchange"])({"enableRateLimit": True, "options": {"defaultType": "future"}})
    await exchange.load_markets()
    CONFIG["symbols"] = await load_symbols(exchange)
    semaphore = asyncio.Semaphore(CONFIG["max_concurrent_requests"])
    sent_signals = set()
    try:
        while True:
            tasks = [analyze_symbol(exchange, sym, sent_signals, semaphore) for sym in CONFIG["symbols"]]
            await asyncio.gather(*tasks)
            await asyncio.sleep(CONFIG["poll_interval"])
    finally:
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
