import functools
import logging
import time

import ccxt
import pandas as pd

log = logging.getLogger(__name__)

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
TIMEFRAMES = ["1m", "5m", "15m", "1h"]
LIMIT = 100

exchange = ccxt.kraken({"enableRateLimit": True})

# Caché de velas OHLCV para no saturar la API de Kraken
_cache: dict = {}
_CACHE_TTL = {
    "1m":  10,    # refrescar cada 10s
    "5m":  30,    # cada 30s
    "15m": 60,    # cada 60s
    "1h":  120,   # cada 2 min (vela horaria casi no cambia en minutos)
    "1w":  3600,  # cada hora (vela semanal casi no cambia)
}

# Velas a pedir por timeframe: 1h necesita 220+ para que EMA 200 tenga historia suficiente
_TF_LIMIT = {
    "1m":  100,
    "5m":  100,
    "15m": 100,
    "1h":  220,
    "1w":  60,
}


def _retry(max_attempts: int = 3, base_delay: float = 2.0):
    """Reintenta la función ante fallos de red con backoff exponencial."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    wait = base_delay * (2 ** attempt)
                    log.warning(f"{func.__name__} falló (intento {attempt+1}/{max_attempts}): {e}. Reintentando en {wait:.0f}s...")
                    time.sleep(wait)
        return wrapper
    return decorator


@_retry(max_attempts=3)
def fetch_ohlcv(symbol: str, timeframe: str = "1m", limit: int | None = None) -> pd.DataFrame:
    """Obtiene velas OHLCV de Kraken con caché por timeframe."""
    if limit is None:
        limit = _TF_LIMIT.get(timeframe, LIMIT)
    now = time.time()
    key = f"{symbol}_{timeframe}"
    ttl = _CACHE_TTL.get(timeframe, 30)

    if key in _cache and (now - _cache[key]["ts"]) < ttl:
        return _cache[key]["df"].copy()

    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)

    _cache[key] = {"df": df, "ts": now}
    return df.copy()


@_retry(max_attempts=3)
def fetch_ticker(symbol: str) -> float:
    """Obtiene el precio actual (último trade) de un par."""
    ticker = exchange.fetch_ticker(symbol)
    return ticker["last"]


def fetch_all() -> dict[str, dict]:
    """Obtiene OHLCV multi-timeframe + precio en vivo para todos los pares."""
    result = {}
    for symbol in SYMBOLS:
        try:
            frames = {}
            for tf in TIMEFRAMES:
                frames[tf] = fetch_ohlcv(symbol, timeframe=tf)
            result[symbol] = {
                "frames": frames,
                "price": fetch_ticker(symbol),
            }
        except Exception as e:
            log.error(f"Error obteniendo datos de {symbol}: {e}")
    return result
