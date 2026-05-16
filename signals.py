import json
import logging
import os
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

# Estado en memoria para no leer disco en cada tick
_state_cache: dict | None = None

# --- Configuración ---
TRADE_AMOUNT = 2000     # USDT
LEVERAGE = 15           # 15x
COOLDOWN_SECONDS = 300  # 5 min entre alertas del mismo par + dirección
MIN_MOVE_PCT = 0.3      # movimiento mínimo esperado (%) para alertar
MIN_CONFIDENCE = 60     # confianza mínima (%) para alertar
MIN_GRID_SPACING_PCT = 0.25  # spacing mínimo por grilla (%) para cubrir fees
BMSB_COOLDOWN_DAYS = 7  # mínimo 7 días entre alertas BMSB del mismo par + dirección


def _load_state() -> dict:
    global _state_cache
    if _state_cache is not None:
        return _state_cache
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                _state_cache = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"state.json corrupto o ilegible, reiniciando: {e}")
            _state_cache = {}
    else:
        _state_cache = {}
    return _state_cache


def _save_state(state: dict) -> None:
    global _state_cache
    _state_cache = state
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_FILE)  # atómico en el mismo filesystem
    except OSError as e:
        log.error(f"No se pudo guardar state.json: {e}")


def evaluate(symbol: str, ind: dict) -> dict | None:
    """Evalúa patrones pre-breakout y predice dirección + magnitud.

    Combina señales de 1m, 5m y 15m para determinar:
    1. ¿Viene un movimiento grande? (squeeze + volumen anómalo)
    2. ¿En qué dirección? (divergencia RSI + MACD pre-cruce + EMA multi-TF)
    3. ¿Es lo suficientemente grande para futuros?

    Solo alerta si: confianza >= 60% Y movimiento esperado >= 0.3%
    """
    long_score = 0
    short_score = 0
    reasons_long = []
    reasons_short = []
    total_signals = 0

    # ===== 1. SQUEEZE (breakout inminente) =====
    sq_1m = ind["squeeze_1m"]
    sq_5m = ind["squeeze_5m"]
    sq_15m = ind["squeeze_15m"]

    breakout_imminent = sq_1m["squeeze"] or sq_5m["squeeze"]

    if sq_1m["squeeze"]:
        total_signals += 1
        if sq_1m["price_position"] > 0.7:
            long_score += 1
            reasons_long.append("BB squeeze 1m (precio arriba)")
        elif sq_1m["price_position"] < 0.3:
            short_score += 1
            reasons_short.append("BB squeeze 1m (precio abajo)")

    if sq_5m["squeeze"]:
        total_signals += 1
        if sq_5m["price_position"] > 0.7:
            long_score += 1
            reasons_long.append("BB squeeze 5m (precio arriba)")
        elif sq_5m["price_position"] < 0.3:
            short_score += 1
            reasons_short.append("BB squeeze 5m (precio abajo)")

    if sq_15m["squeeze"]:
        total_signals += 1
        # Squeeze en 15m = movimiento MUY grande inminente
        if sq_15m["price_position"] > 0.6:
            long_score += 2
            reasons_long.append("BB squeeze 15m ⚡ (movimiento grande)")
        elif sq_15m["price_position"] < 0.4:
            short_score += 2
            reasons_short.append("BB squeeze 15m ⚡ (movimiento grande)")

    # ===== 2. DIVERGENCIA RSI (reversión inminente) =====
    div_1m = ind["rsi_div_1m"]
    div_5m = ind["rsi_div_5m"]

    if div_1m["divergence"] == "BULL":
        long_score += 1
        total_signals += 1
        reasons_long.append(f"Divergencia alcista RSI 1m ({div_1m['rsi']:.0f})")
    elif div_1m["divergence"] == "BEAR":
        short_score += 1
        total_signals += 1
        reasons_short.append(f"Divergencia bajista RSI 1m ({div_1m['rsi']:.0f})")

    if div_5m["divergence"] == "BULL":
        long_score += 2  # divergencia en 5m pesa más
        total_signals += 1
        reasons_long.append(f"Divergencia alcista RSI 5m ({div_5m['rsi']:.0f})")
    elif div_5m["divergence"] == "BEAR":
        short_score += 2
        total_signals += 1
        reasons_short.append(f"Divergencia bajista RSI 5m ({div_5m['rsi']:.0f})")

    # RSI extremo (sobre-compra / sobre-venta)
    rsi = div_1m["rsi"]
    if rsi > 75:
        short_score += 1
        total_signals += 1
        reasons_short.append(f"RSI sobrecompra ({rsi:.0f})")
    elif rsi < 25:
        long_score += 1
        total_signals += 1
        reasons_long.append(f"RSI sobreventa ({rsi:.0f})")

    # ===== 3. PICO DE VOLUMEN (acumulación/distribución) =====
    vol = ind["vol_spike_1m"]
    if vol["vol_spike"]:
        total_signals += 1
        if vol["candle_dir"] == "LONG":
            long_score += 2
            reasons_long.append(f"Volumen anómalo {vol['vol_ratio']:.1f}x (acumulación)")
        else:
            short_score += 2
            reasons_short.append(f"Volumen anómalo {vol['vol_ratio']:.1f}x (distribución)")

    # ===== 4. MACD PRE-CRUCE (momentum cambiando) =====
    macd_1m = ind["macd_pre_1m"]
    macd_5m = ind["macd_pre_5m"]

    if macd_1m["pre_cross"] == "LONG":
        long_score += 1
        total_signals += 1
        reasons_long.append("MACD cruce alcista inminente 1m")
    elif macd_1m["pre_cross"] == "SHORT":
        short_score += 1
        total_signals += 1
        reasons_short.append("MACD cruce bajista inminente 1m")

    if macd_5m["pre_cross"] == "LONG":
        long_score += 2
        total_signals += 1
        reasons_long.append("MACD cruce alcista inminente 5m")
    elif macd_5m["pre_cross"] == "SHORT":
        short_score += 2
        total_signals += 1
        reasons_short.append("MACD cruce bajista inminente 5m")

    # ===== 5. EMA MULTI-TIMEFRAME (confirma dirección) =====
    ema_1m = ind["ema_1m"]
    ema_5m = ind["ema_5m"]
    ema_15m = ind["ema_15m"]

    # Alineación multi-TF: si los 3 timeframes alinean, pesa mucho
    all_bull = ema_1m["ema_bullish"] and ema_5m["ema_bullish"] and ema_15m["ema_bullish"]
    all_bear = not ema_1m["ema_bullish"] and not ema_5m["ema_bullish"] and not ema_15m["ema_bullish"]

    if all_bull:
        long_score += 2
        total_signals += 1
        reasons_long.append("EMA alineadas BULL (1m+5m+15m)")
    elif all_bear:
        short_score += 2
        total_signals += 1
        reasons_short.append("EMA alineadas BEAR (1m+5m+15m)")

    # ===== 6. CASCADA DE MOMENTUM (movimiento fuerte formándose) =====
    cascade_1m = ind.get("cascade_1m", {"cascade": False, "early_warning": False})
    cascade_5m = ind.get("cascade_5m", {"cascade": False, "early_warning": False})
    vol_expand_1m = ind.get("vol_expand_1m", {"expanding": False})
    vol_expand_5m = ind.get("vol_expand_5m", {"expanding": False})
    predictive_detected = False

    # Cascada completa en 1m: 3+ velas acelerando → alta probabilidad de continuación
    if cascade_1m.get("cascade"):
        total_signals += 1
        predictive_detected = True
        accel = cascade_1m["acceleration"]
        n = cascade_1m["consecutive"]
        if cascade_1m["direction"] == "LONG":
            long_score += 3
            reasons_long.append(f"🔮 Cascada alcista 1m ({n} velas, accel {accel:.1f}x)")
        else:
            short_score += 3
            reasons_short.append(f"🔮 Cascada bajista 1m ({n} velas, accel {accel:.1f}x)")

    # Alerta temprana en 1m: 2 velas con fuerte aceleración → precursor
    elif cascade_1m.get("early_warning"):
        total_signals += 1
        predictive_detected = True
        accel = cascade_1m["acceleration"]
        if cascade_1m["direction"] == "LONG":
            long_score += 2
            reasons_long.append(f"🔮 Momentum acelerando 1m (accel {accel:.1f}x)")
        else:
            short_score += 2
            reasons_short.append(f"🔮 Momentum acelerando 1m (accel {accel:.1f}x)")

    # Cascada en 5m: más confiable, movimiento más grande
    if cascade_5m.get("cascade"):
        total_signals += 1
        predictive_detected = True
        accel = cascade_5m["acceleration"]
        n = cascade_5m["consecutive"]
        if cascade_5m["direction"] == "LONG":
            long_score += 4
            reasons_long.append(f"🔮 Cascada alcista 5m ({n} velas, accel {accel:.1f}x)")
        else:
            short_score += 4
            reasons_short.append(f"🔮 Cascada bajista 5m ({n} velas, accel {accel:.1f}x)")

    elif cascade_5m.get("early_warning"):
        total_signals += 1
        predictive_detected = True
        accel = cascade_5m["acceleration"]
        if cascade_5m["direction"] == "LONG":
            long_score += 2
            reasons_long.append(f"🔮 Momentum acelerando 5m (accel {accel:.1f}x)")
        else:
            short_score += 2
            reasons_short.append(f"🔮 Momentum acelerando 5m (accel {accel:.1f}x)")

    # ===== 7. EXPANSIÓN DE VOLATILIDAD (explosión inminente) =====
    if vol_expand_1m.get("expanding"):
        total_signals += 1
        predictive_detected = True
        ratio = vol_expand_1m["ratio"]
        label = "squeeze→explosión" if vol_expand_1m.get("squeeze_break") else f"ATR {ratio:.1f}x"
        # Dirección la damos por EMA o cascada
        if ema_1m["ema_bullish"]:
            long_score += 2
            reasons_long.append(f"⚡ Volatilidad expandiendo 1m ({label})")
        else:
            short_score += 2
            reasons_short.append(f"⚡ Volatilidad expandiendo 1m ({label})")

    if vol_expand_5m.get("expanding"):
        total_signals += 1
        predictive_detected = True
        ratio = vol_expand_5m["ratio"]
        label = "squeeze→explosión" if vol_expand_5m.get("squeeze_break") else f"ATR {ratio:.1f}x"
        if ema_5m["ema_bullish"]:
            long_score += 2
            reasons_long.append(f"⚡ Volatilidad expandiendo 5m ({label})")
        else:
            short_score += 2
            reasons_short.append(f"⚡ Volatilidad expandiendo 5m ({label})")

    # ===== DECISIÓN FINAL =====
    if total_signals == 0:
        return None

    # Necesitamos al menos 1 señal de breakout + 1 de dirección
    # Señales predictivas (cascada/volatilidad) pasan el gate automáticamente
    if not breakout_imminent and not vol["vol_spike"] and not predictive_detected:
        # Sin señal de que viene un movimiento, no alertar
        if long_score < 5 and short_score < 5:
            return None

    max_score = max(long_score, short_score)
    total_possible = total_signals * 2  # peso máximo teórico
    confidence = min(max_score / max(total_possible, 1) * 100, 99)

    if max_score < 3:
        return None

    if confidence < MIN_CONFIDENCE:
        return None

    direction = "LONG" if long_score >= short_score else "SHORT"
    reasons = reasons_long if direction == "LONG" else reasons_short

    # --- Estimar movimiento esperado ---
    atr = vol["atr"]
    price = ind["price"]

    # Más señales alineadas = movimiento más fuerte esperado
    multiplier = 1 + (max_score / 10)
    expected_move = atr * multiplier
    move_pct = expected_move / price * 100

    if move_pct < MIN_MOVE_PCT:
        return None  # movimiento muy chico para futuros

    # --- Trade simulado ---
    position_size = TRADE_AMOUNT * LEVERAGE
    if direction == "LONG":
        entry = price
        target = price + expected_move
        stop = price - (expected_move * 0.4)
    else:
        entry = price
        target = price - expected_move
        stop = price + (expected_move * 0.4)

    expected_pnl = position_size * (expected_move / price)
    risk_pnl = position_size * (expected_move * 0.4 / price)

    # --- Grid Bot de Futuros ---
    # Rango: basado en ATR × confianza para capturar el movimiento esperado
    # ATR 15m da mejor estimación de rango real que el ATR de 1m
    atr_15m = ind.get("atr_15m", atr)
    grid_atr = max(atr, atr_15m)  # usar el ATR más amplio

    # Rango proporcional a la confianza: más confianza → rango más ajustado
    # Menos confianza → rango más amplio para capturar más escenarios
    if confidence >= 80:
        range_mult = 2.5   # alta confianza → rango ajustado (2.5 ATR)
    elif confidence >= 70:
        range_mult = 3.5   # buena confianza → rango medio
    else:
        range_mult = 4.5   # moderada → rango amplio

    grid_range = grid_atr * range_mult

    if direction == "LONG":
        grid_lower = price - (grid_range * 0.3)  # 30% abajo (stop)
        grid_upper = price + (grid_range * 0.7)  # 70% arriba (profit)
    else:
        grid_lower = price - (grid_range * 0.7)  # 70% abajo (profit)
        grid_upper = price + (grid_range * 0.3)  # 30% arriba (stop)

    grid_range_pct = (grid_upper - grid_lower) / price * 100

    # Número de grillas dinámico: spacing >= MIN_GRID_SPACING_PCT para ser rentable
    num_grids = max(5, int(grid_range_pct / MIN_GRID_SPACING_PCT))

    grid_spacing_pct = grid_range_pct / num_grids
    grid_spacing_usd = (grid_upper - grid_lower) / num_grids
    profit_per_grid = TRADE_AMOUNT * LEVERAGE * (grid_spacing_pct / 100)
    fee_per_grid = TRADE_AMOUNT * LEVERAGE * 0.04 / 100  # ~0.04% round-trip
    net_per_grid = profit_per_grid - fee_per_grid

    # Liquidación estimada (margen aislado)
    liq_distance_pct = 100 / LEVERAGE * 0.95  # ~95% del margen
    if direction == "LONG":
        liq_price = price * (1 - liq_distance_pct / 100)
    else:
        liq_price = price * (1 + liq_distance_pct / 100)

    # --- Cooldown anti-spam ---
    state = _load_state()
    now = time.time()
    key = f"{symbol}_{direction}"
    last_alert = state.get(key, {}).get("last_alert_time", 0)

    if (now - last_alert) < COOLDOWN_SECONDS:
        return None

    state[key] = {
        "direction": direction,
        "last_alert_time": now,
        "confidence": confidence,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    _save_state(state)

    return {
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "price": price,
        "rsi": div_1m["rsi"],
        "reasons": reasons,
        "move_pct": move_pct,
        "trade": {
            "amount": TRADE_AMOUNT,
            "leverage": LEVERAGE,
            "position_size": position_size,
            "entry": entry,
            "target": target,
            "stop": stop,
            "move_pct": move_pct,
            "expected_pnl": expected_pnl,
            "risk_pnl": risk_pnl,
        },
        "grid": {
            "lower": grid_lower,
            "upper": grid_upper,
            "num_grids": num_grids,
            "range_pct": grid_range_pct,
            "spacing_pct": grid_spacing_pct,
            "spacing_usd": grid_spacing_usd,
            "profit_per_grid": profit_per_grid,
            "fee_per_grid": fee_per_grid,
            "net_per_grid": net_per_grid,
            "liq_price": liq_price,
        },
    }


def evaluate_bmsb(symbol: str, bmsb: dict | None) -> dict | None:
    """Detecta cruce del Bull Market Support Band y genera alerta macro.

    Solo alerta cuando la zona CAMBIA:
        BEAR / NEUTRAL  →  BULL   ⟹ cruce alcista (precio superó ambas bandas)
        BULL / NEUTRAL  →  BEAR   ⟹ cruce bajista (precio cayó bajo ambas bandas)

    NEUTRAL nunca dispara alerta por sí misma.
    Cooldown de 7 días por par + dirección para evitar re-alertas.
    """
    if not bmsb:
        return None

    curr_zone = bmsb["zone"]
    state = _load_state()
    now = time.time()

    zone_key = f"{symbol}_BMSB_zone"
    prev_zone = state.get(zone_key, {}).get("zone", "UNKNOWN")

    # Actualizar zona almacenada siempre (sin importar si alerta)
    state[zone_key] = {
        "zone": curr_zone,
        "updated": datetime.now(timezone.utc).isoformat(),
    }

    # Sin cambio de zona → no alertar
    if curr_zone == prev_zone:
        _save_state(state)
        return None

    # Zona NEUTRAL → registrar cambio pero no alertar
    if curr_zone == "NEUTRAL":
        _save_state(state)
        return None

    # Solo alertar en cruces hacia BULL o BEAR
    cooldown_key = f"{symbol}_BMSB_{curr_zone}"
    last_alert = state.get(cooldown_key, {}).get("last_alert_time", 0)
    cooldown_secs = BMSB_COOLDOWN_DAYS * 86400

    if (now - last_alert) < cooldown_secs:
        _save_state(state)
        return None

    state[cooldown_key] = {
        "direction": curr_zone,
        "last_alert_time": now,
        "prev_zone": prev_zone,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    _save_state(state)

    return {
        "symbol": symbol,
        "type": "BMSB",
        "direction": curr_zone,       # "BULL" o "BEAR"
        "prev_zone": prev_zone,
        "price": bmsb["price"],
        "sma20": bmsb["sma20"],
        "ema21": bmsb["ema21"],
        "dist_sma20_pct": bmsb["dist_sma20_pct"],
        "dist_ema21_pct": bmsb["dist_ema21_pct"],
    }
