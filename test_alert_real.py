"""Simula un escenario de señal LONG y envía la alerta REAL a Telegram."""

import json
import os

# Resetear cooldown para que no bloquee
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")
with open(STATE_FILE, "w") as f:
    json.dump({}, f)

import signals
import notifier


# Construir indicadores sintéticos que simulan un escenario de LONG ideal:
# - Squeeze de Bollinger en 1m con precio pegado a la banda superior
# - Divergencia alcista RSI en 5m (precio baja pero RSI sube)
# - MACD en 5m a punto de cruzar al alza
# - Todas las EMAs alineadas alcistas
# - ATR alto (mercado volátil)

ind = {
    "price": 85000.0,
    "squeeze_1m":  {"squeeze": True,  "bb_width": 0.3, "bb_width_pctile": 15, "price_position": 0.85},
    "squeeze_5m":  {"squeeze": False, "bb_width": 0.8, "bb_width_pctile": 55, "price_position": 0.60},
    "squeeze_15m": {"squeeze": False, "bb_width": 1.0, "bb_width_pctile": 60, "price_position": 0.55},
    "rsi_div_1m":  {"divergence": "NONE", "rsi": 52.0},
    "rsi_div_5m":  {"divergence": "BULL", "rsi": 38.0},
    "vol_spike_1m": {"vol_spike": False, "vol_ratio": 1.1, "price_move_ratio": 0.5, "candle_dir": "LONG", "atr": 500.0},
    "macd_pre_1m": {"pre_cross": "NONE", "macd_hist": 0.05, "convergence_rate": 0.08},
    "macd_pre_5m": {"pre_cross": "LONG", "macd_hist": -0.02, "convergence_rate": 0.35},
    "ema_1m":  {"ema_bullish": True,  "ema9": 85050, "ema21": 84920, "ema_gap_pct": 0.15},
    "ema_5m":  {"ema_bullish": True,  "ema9": 85100, "ema21": 84950, "ema_gap_pct": 0.18},
    "ema_15m": {"ema_bullish": True,  "ema9": 85080, "ema21": 84900, "ema_gap_pct": 0.21},
}

print("=" * 60)
print("  SIMULACIÓN → Enviando alerta REAL a Telegram")
print("=" * 60)
print()
print("  Escenario: BTC/USDT LONG")
print("  - Squeeze BB 1m (precio en banda superior)")
print("  - Divergencia alcista RSI 5m")
print("  - MACD 5m cruce alcista inminente")
print("  - EMAs 1m+5m+15m todas alcistas")
print()

signal = signals.evaluate("BTC/USDT", ind)

if signal:
    print(f"  ✅ Señal generada: {signal['direction']} {signal['confidence']:.0f}%")
    print(f"     Movimiento esperado: {signal['move_pct']:+.2f}%")
    print(f"     Entrada: ${signal['trade']['entry']:,.2f}")
    print(f"     Target:  ${signal['trade']['target']:,.2f}")
    print(f"     Stop:    ${signal['trade']['stop']:,.2f}")
    print(f"     PnL est: +${signal['trade']['expected_pnl']:,.2f}")
    print()
    print("  Enviando a Telegram...")
    ok = notifier.notify(signal)
    if ok:
        print("  ✅ ¡Alerta enviada! Revisa tu Telegram.")
    else:
        print("  ❌ Error al enviar. Revisa el .env con las credenciales.")
else:
    print("  ❌ No se generó señal (revisa los indicadores)")
