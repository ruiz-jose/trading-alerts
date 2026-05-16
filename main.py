"""Trading Day Bot — Predicción de movimientos para Futuros.

Analiza BTC/USDT, ETH/USDT, SOL/USDT cada segundo usando múltiples
timeframes (1m, 5m, 15m) para detectar movimientos ANTES de que ocurran:
- Bollinger Band squeeze (volatilidad comprimida = breakout inminente)
- Divergencia RSI/precio (reversión inminente)
- Pico de volumen sin movimiento (acumulación/distribución)
- MACD pre-cruce (momentum cambiando)
- EMA multi-timeframe (confirmación de dirección)

Cuando detecta un movimiento significativo inminente (>= 0.3%), envía
por Telegram la predicción LONG o SHORT con trade de 1000 USDT × 5x.

Uso:
    python main.py          # ejecuta un análisis y sale
    python main.py --live   # loop cada segundo (Ctrl+C para parar)
"""

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import data
import indicators
import notifier
import signals
import web

# ── Logging ──────────────────────────────────────────────────────────────────
_LOG_FILE = Path(__file__).parent / "trading-bot.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

TICK_INTERVAL = 1.0   # segundos entre ticks de futuros
BMSB_INTERVAL = 60.0  # segundos entre chequeos del BMSB semanal

_last_bmsb_check: float = 0.0


def run_bmsb_check() -> None:
    """Chequea el Bull Market Support Band (1W) para cada par.

    Corre cada BMSB_INTERVAL segundos. Solo genera alerta cuando el precio
    cruza las bandas semanales (cambio de zona BULL ↔ BEAR).
    """
    global _last_bmsb_check
    now = time.monotonic()
    if now - _last_bmsb_check < BMSB_INTERVAL:
        return
    _last_bmsb_check = now

    for symbol in data.SYMBOLS:
        try:
            df_1w = data.fetch_ohlcv(symbol, timeframe="1w", limit=60)
            live = data.fetch_ticker(symbol)
            bmsb = indicators.compute_bmsb(df_1w, live_price=live)
            signal = signals.evaluate_bmsb(symbol, bmsb)
            if signal:
                log.info(
                    f"🌐 BMSB  {symbol}  {signal['direction']}  "
                    f"precio=${signal['price']:,.2f}  "
                    f"SMA20=${signal['sma20']:,.2f}  EMA21=${signal['ema21']:,.2f}"
                )
                notifier.notify_bmsb(signal)
        except Exception as e:
            log.exception(f"Error en BMSB check {symbol}: {e}")


def run_tick() -> None:
    """Un tick: obtener datos multi-TF → detectar pre-breakout → alertar."""
    all_data = data.fetch_all()
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

    if not all_data:
        msg = "fetch_all() devolvió vacío — exchange inaccesible desde este servidor"
        log.error(msg)
        web.push_error(msg)
        return

    for symbol, info in all_data.items():
        # Enviar precio en vivo al dashboard
        web.push_scan({"symbol": symbol, "price": info["price"], "ts": ts})

        try:
            ind = indicators.compute(info["frames"], live_price=info["price"])
            signal = signals.evaluate(symbol, ind)

            if signal:
                d = signal["direction"]
                c = signal["confidence"]
                m = signal["move_pct"]
                pnl = signal["trade"]["expected_pnl"]
                log.info(f"⚡ ALERTA  {symbol}  {d}  conf={c:.0f}%  mov={m:+.2f}%  PnL=${pnl:,.2f}")
                notifier.notify(signal)
            else:
                log.debug(f"{symbol}: escaneando...")
        except Exception as e:
            log.exception(f"Error procesando {symbol}: {e}")


def main() -> None:
    if "--live" in sys.argv:
        log.info("=" * 60)
        log.info("  TRADING ALERTS — Predicción Pre-Breakout")
        log.info("=" * 60)
        log.info(f"  Pares      : {', '.join(data.SYMBOLS)}")
        log.info(f"  Timeframes : {', '.join(data.TIMEFRAMES)}")
        log.info(f"  Trade      : {signals.TRADE_AMOUNT} USDT × {signals.LEVERAGE}x")
        log.info(f"  Mov. mín.  : {signals.MIN_MOVE_PCT}%")
        log.info(f"  Confianza  : {signals.MIN_CONFIDENCE}%")
        log.info(f"  Cooldown   : {signals.COOLDOWN_SECONDS}s")
        log.info(f"  Log        : {_LOG_FILE}")
        log.info("=" * 60)

        # En local abre el browser; en cloud (sin TTY) no lo abre
        is_local = sys.stdout.isatty()
        web.start(open_browser=is_local)

        log.info("  Escaneando cada segundo... Ctrl+C para detener")
        log.info("=" * 60)

        try:
            while True:
                tick_start = time.monotonic()
                run_bmsb_check()  # no-op si no pasaron 60s
                run_tick()
                elapsed = time.monotonic() - tick_start
                sleep_time = max(0.0, TICK_INTERVAL - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except KeyboardInterrupt:
            log.info("Bot detenido por el usuario.")
    else:
        log.info("Modo único: ejecutando un tick de análisis.")
        run_tick()


if __name__ == "__main__":
    main()
