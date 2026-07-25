import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime, timedelta
from database import get_all_users, get_user_settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

PRICE_BUFFER = {}
BTC_TREND_CACHE = {'trend': 'NEUTRAL', 'change': 0.0}
BUFFER_RETENTION_MIN = 130 

msg_semaphore = asyncio.Semaphore(10)

EXCHANGE_EMOJIS = {
    'binance': '👘BINANCE', 'bybit': '🎓BYBIT', 'mexc': '🧩MEXC',
    'okx': '🎹OKX', 'kucoin': '🥏KUCOIN', 'bitget': '⚗️BITGET',
    'gate': '🐠GATEIO', 'bingx': '🧊BINGX'
}

class MarketEngine:
    def __init__(self, bot):
        self.bot = bot
        self.exchanges = {}
        self.running = True
        self.alert_history = {} 
    
    async def init_exchanges(self):
        common_opts = {
            'enableRateLimit': True, 
            'timeout': 10000,
            'adjustForTimeDifference': True,
        }
        
        exchange_configs = {
            'binance': {'class': ccxt.binance, 'type': 'future'},
            'bybit': {'class': ccxt.bybit, 'type': 'future'},
            'mexc': {'class': ccxt.mexc, 'type': 'swap'},
            'okx': {'class': ccxt.okx, 'type': 'swap'},
            'kucoin': {'class': ccxt.kucoin, 'type': 'future'},
            'bitget': {'class': ccxt.bitget, 'type': 'swap'},
            'gate': {'class': ccxt.gate, 'type': 'swap'}, 
            'bingx': {'class': ccxt.bingx, 'type': 'swap'}
        }

        logger.info("⚡️ Connecting to 8 Exchanges...")
        
        for name, cfg in exchange_configs.items():
            opts = common_opts.copy()
            opts['options'] = {'defaultType': cfg['type']}
            if name == 'gate':
                opts['fetchCurrencies'] = False
                opts['urls'] = {'api': 'https://api.gateio.ws/api/v4'}
            self.exchanges[name] = cfg['class'](opts)

        tasks = [self.preload_markets(name) for name in self.exchanges]
        await asyncio.gather(*tasks)
        logger.info("✅ System Ready.")

    async def preload_markets(self, name):
        try: await self.exchanges[name].load_markets()
        except: pass

    async def close_exchanges(self):
        for ex in self.exchanges.values(): await ex.close()

    def normalize_symbol(self, raw_symbol, exchange_name):
        try:
            s = raw_symbol.split(':')[0] 
            s = s.replace('-SWAP', '').replace('-PERP', '') 
            if exchange_name in ['gate', 'mexc'] and '_' in s: s = s.replace('_', '/')
            if '/' not in s and 'USDT' in s: s = s.replace('USDT', '/USDT')
            return s
        except: return raw_symbol

    async def fetch_tickers_safe(self, exchange_name):
        try:
            exchange = self.exchanges[exchange_name]
            tickers = await asyncio.wait_for(exchange.fetch_tickers(), timeout=7.0)
            return exchange_name, tickers
        except: return exchange_name, {}

    async def get_market_context(self, exchange_name, symbol, user_settings):
        exchange = self.exchanges[exchange_name]
        data = {
            'rsi': 50.0, 'vol_factor': 0.0, 'score': 1, 
            'oi': "N/A", 'vol24': 0.0, 'volatility': 'Норма',
            'funding': 'N/A',
            'sr': {'res': 0, 'res_dist': 0, 'sup': 0, 'sup_dist': 0}
        }
        
        try:
            tf = user_settings.get('interval', 5)
            tf_str = '5m' if tf <= 5 else '15m' if tf <= 15 else '1h'
            
            tasks = {
                "ohlcv": exchange.fetch_ohlcv(symbol, timeframe=tf_str, limit=30),
                "ticker": exchange.fetch_ticker(symbol)
            }
            if user_settings.get('show_oi_change'): tasks["oi"] = exchange.fetch_open_interest(symbol)
            if user_settings.get('show_funding'): tasks["funding"] = exchange.fetch_funding_rate(symbol)
            
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            res_map = dict(zip(tasks.keys(), results))

            if "ohlcv" in res_map and isinstance(res_map["ohlcv"], list) and res_map["ohlcv"]:
                df = pd.DataFrame(res_map["ohlcv"], columns=['t', 'o', 'h', 'l', 'c', 'v'])
                curr_close = df['c'].iloc[-1]

                delta = df['c'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rs = gain / loss
                rsi_val = 100 - (100 / (1 + rs))
                data['rsi'] = round(rsi_val.iloc[-1], 1) if not pd.isna(rsi_val.iloc[-1]) else 50.0
                
                avg_vol = df['v'].rolling(20).mean().iloc[-1]
                if avg_vol > 0: data['vol_factor'] = round(df['v'].iloc[-1] / avg_vol, 1)

                df['hl_pct'] = ((df['h'] - df['l']) / df['l']) * 100
                atr = df['hl_pct'].rolling(14).mean().iloc[-1]
                if atr > 1.5: data['volatility'] = "Высокая"
                elif atr < 0.3: data['volatility'] = "Низкая"

                res = df['h'].max()
                sup = df['l'].min()
                data['sr']['res'] = res
                data['sr']['res_dist'] = ((res - curr_close) / curr_close) * 100
                data['sr']['sup'] = sup
                data['sr']['sup_dist'] = ((curr_close - sup) / curr_close) * 100

            if "ticker" in res_map and isinstance(res_map["ticker"], dict): 
                data['vol24'] = res_map["ticker"].get('quoteVolume', 0)

            if "oi" in res_map and isinstance(res_map["oi"], dict):
                val = float(res_map["oi"]['openInterestAmount'])
                if val > 1_000_000: data['oi'] = f"{val/1_000_000:.1f}M"
                elif val > 1_000: data['oi'] = f"{val/1_000:.1f}K"
                else: data['oi'] = f"{val:.0f}"

            if "funding" in res_map and isinstance(res_map["funding"], dict):
                data['funding'] = f"{res_map['funding']['fundingRate']*100:.4f}%"
            
            score = 1
            if data['vol24'] > 1_000_000: score += 1
            if data['vol_factor'] > 2.0: score += 1
            if data['vol_factor'] > 4.0: score += 1
            if BTC_TREND_CACHE['trend'] != "NEUTRAL": score += 1
            data['score'] = min(score, 5)

        except: pass
        return data

    async def process_market_data(self):
        logger.info(">>> ENGINE STARTED.")
        last_btc_update = datetime.now() - timedelta(minutes=5)

        while self.running:
            try:
                loop_start = datetime.now()
                if (datetime.now() - last_btc_update).total_seconds() > 60:
                    asyncio.create_task(self.update_btc_trend())
                    last_btc_update = datetime.now()

                tasks = [self.fetch_tickers_safe(name) for name in self.exchanges]
                for future in asyncio.as_completed(tasks, timeout=12.0):
                    try:
                        exchange_name, tickers = await future
                        if not tickers: continue
                        if exchange_name not in PRICE_BUFFER: PRICE_BUFFER[exchange_name] = {}
                        for raw_sym, data in tickers.items():
                            try:
                                if 'USDT' not in raw_sym: continue
                                clean_sym = self.normalize_symbol(raw_sym, exchange_name)
                                price = data.get('last')
                                if not price or price <= 0: continue
                                if clean_sym not in PRICE_BUFFER[exchange_name]: PRICE_BUFFER[exchange_name][clean_sym] = {}
                                PRICE_BUFFER[exchange_name][clean_sym][loop_start] = price
                            except: pass
                    except: pass
                
                users = await get_all_users()
                
                parsed_users = []
                for u in users:
                    if u.get('is_paused'): continue
                    try: exc_list = set(json.loads(u['exchanges']))
                    except: exc_list = set()
                    parsed_users.append({'u': u, 'exc': exc_list})

                for ex_name, symbols in PRICE_BUFFER.items():
                    active_users = [item['u'] for item in parsed_users if ex_name in item['exc']]
                    if not active_users: continue
                    
                    active_intervals = set(u['interval'] for u in active_users)

                    for sym, history in symbols.items():
                        try:
                            if loop_start not in history: continue
                            curr_price = history[loop_start]
                            
                            for mins in active_intervals:
                                target_time = loop_start - timedelta(minutes=mins)
                                past_ts = min(history.keys(), key=lambda x: abs((x - target_time).total_seconds()), default=None)
                                
                                if not past_ts or abs((past_ts - target_time).total_seconds()) > 30: continue
                                old_price = history[past_ts]
                                pct_change = ((curr_price - old_price) / old_price) * 100
                                
                                for user in active_users:
                                    if user['interval'] != mins or abs(pct_change) < user['threshold']: continue
                                    akey = (user['user_id'], ex_name, sym, mins)
                                    if akey in self.alert_history and (datetime.now() - self.alert_history[akey]).total_seconds() < (mins * 60): continue
                                    
                                    if user.get('filter_btc_enabled'):
                                        trend = BTC_TREND_CACHE['trend']
                                        if (pct_change > 0 and trend == "BEARISH") or (pct_change < 0 and trend == "BULLISH"): continue

                                    asyncio.create_task(self.process_alert(user['user_id'], ex_name, sym, curr_price, old_price, pct_change, mins))
                                    self.alert_history[akey] = datetime.now()
                        except: pass
                
                cutoff = loop_start - timedelta(minutes=BUFFER_RETENTION_MIN)
                for exc in PRICE_BUFFER:
                    for s in list(PRICE_BUFFER[exc].keys()):
                        PRICE_BUFFER[exc][s] = {ts: p for ts, p in PRICE_BUFFER[exc][s].items() if ts > cutoff}
                
                alert_cutoff = loop_start - timedelta(hours=3)
                self.alert_history = {k: v for k, v in self.alert_history.items() if v > alert_cutoff}

                elapsed = (datetime.now() - loop_start).total_seconds()
                await asyncio.sleep(max(1.0, 3.0 - elapsed))
            except Exception as e:
                logger.error(f"Critical Loop Error: {e}") 
                await asyncio.sleep(2)

    async def update_btc_trend(self):
        try:
            ohlcv = await self.exchanges['binance'].fetch_ohlcv('BTC/USDT', '15m', limit=2)
            ch = ((ohlcv[-1][4] - ohlcv[-1][1]) / ohlcv[-1][1]) * 100
            BTC_TREND_CACHE['trend'] = "BULLISH" if ch > 0.15 else "BEARISH" if ch < -0.15 else "NEUTRAL"
        except: pass

    async def process_alert(self, user_id, exchange, symbol, price, old_price, change, interval):
        try:
            user_set = await get_user_settings(user_id)
            if not user_set or user_set.get('is_paused'): return

            if user_set.get('sleep_enabled'):
                curr_utc_hour = datetime.utcnow().hour
                s_from = user_set.get('sleep_from', 0)
                s_to = user_set.get('sleep_to', 8)
                
                if s_from < s_to:
                    if s_from <= curr_utc_hour < s_to: return
                elif s_from > s_to:
                    if curr_utc_hour >= s_from or curr_utc_hour < s_to: return
                else:
                    if curr_utc_hour == s_from: return

            ctx = await self.get_market_context(exchange, symbol, user_set)
            
            if user_set['rsi_enabled'] and ctx:
                if (change > 0 and ctx['rsi'] > user_set['rsi_pump_limit']) or (change < 0 and ctx['rsi'] < user_set['rsi_dump_limit']):
                    return

            pair = symbol.split('/')[0]
            if user_set['show_hashtag']: pair = f"#{pair}"
            
            emoji = "🟢" if change > 0 else "🔴"
            side = "LONG" if change > 0 else "SHORT"
            exch_fmt = EXCHANGE_EMOJIS.get(exchange, exchange.upper())
            
            fmt = lambda x: f"{x:.8f}".rstrip('0').rstrip('.') if x < 10 else f"{x:.2f}"
            
            msg = [f"<b>{pair}</b> | {exch_fmt} | {side} {emoji}"]
            msg.append(f"{fmt(old_price)} ➔ <b>{fmt(price)}</b> ({change:+.2f}%)")
            msg.append("")
            
            if ctx:
                info_block = []
                if user_set.get('show_vol24') and ctx['vol24'] > 0:
                    v = ctx['vol24']
                    if v >= 1_000_000: v_str = f"${v/1_000_000:.1f}M"
                    elif v >= 1_000: v_str = f"${v/1_000:.1f}K"
                    else: v_str = f"${v:.0f}"
                    info_block.append(f"Объем 24ч: {v_str}")

                if user_set['rsi_enabled']: info_block.append(f"Индикатор RSI: {ctx['rsi']}")
                if user_set.get('show_volatility'): info_block.append(f"Волатильность: {ctx['volatility']}")
                if user_set.get('show_oi_change') and ctx['oi'] != "N/A": info_block.append(f"Открытый интерес: {ctx['oi']}")
                if user_set.get('show_funding') and ctx['funding'] != 'N/A': info_block.append(f"Фандинг: {ctx['funding']}")
                
                if user_set.get('show_sr_levels'):
                    res_val, sup_val = ctx['sr']['res'], ctx['sr']['sup']
                    if change > 0:
                        t = f"{fmt(res_val)} (+{ctx['sr']['res_dist']:.1f}%)" if res_val > 0 else "N/A"
                        info_block.append(f"Цель (Res): {t}")
                    else:
                        t = f"{fmt(sup_val)} (-{ctx['sr']['sup_dist']:.1f}%)" if sup_val > 0 else "N/A"
                        info_block.append(f"Цель (Sup): {t}")

                msg.extend(info_block)
                if info_block: msg.append("")

                filter_block = []
                if user_set.get('show_signal_strength'): filter_block.append(f"Приоритет сигнала: {'★' * ctx['score']}")
                if user_set.get('show_volume_anomaly') and ctx['vol_factor'] > 0.1: filter_block.append(f"Аномалия сигнала: <b>x{ctx['vol_factor']}</b> ⚠️")
                msg.extend(filter_block)

            async with msg_semaphore:
                final_check = await get_user_settings(user_id)
                if not final_check or final_check.get('is_paused'): return
                await self.bot.send_message(user_id, "\n".join(msg), parse_mode="HTML")
                await asyncio.sleep(0.05)

        except Exception as e:
            if "flood" in str(e).lower(): await asyncio.sleep(10)

async def run_screener(bot):
    engine = MarketEngine(bot)
    await engine.init_exchanges()
    try: await engine.process_market_data()
    finally: await engine.close_exchanges()