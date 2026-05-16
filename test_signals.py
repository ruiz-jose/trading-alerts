"""Test de simulación: muestra exactamente cuándo se genera una señal.

Usa datos sintéticos (sin conectar a Binance) para demostrar los filtros
de signals.evaluate() paso a paso.
"""

import json
import os
import time

# Resetear state.json para que el cooldown no interfiera
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")
with open(STATE_FILE, "w") as f:
    json.dump({}, f)

import signals


def make_indicators(
    # Squeeze
    sq1_squeeze=False, sq1_pos=0.5,
    sq5_squeeze=False, sq5_pos=0.5,
    sq15_squeeze=False, sq15_pos=0.5,
    # RSI divergencia
    rsi_div_1m="NONE", rsi_1m=50.0,
    rsi_div_5m="NONE", rsi_5m=50.0,
    # Volumen
    vol_spike=False, vol_ratio=1.0, price_move_ratio=0.5, candle_dir="LONG", atr=50.0,
    # MACD
    macd_1m="NONE", macd_5m="NONE",
    # EMA
    ema_1m_bull=True, ema_5m_bull=True, ema_15m_bull=True,
    # Predictivos (cascada + volatilidad)
    cascade_1m=None, cascade_5m=None,
    vol_expand_1m=None, vol_expand_5m=None,
    # Precio
    price=85000.0,
):
    """Construye un dict de indicadores sintético idéntico al de indicators.compute()."""
    _cascade_off = {"cascade": False, "early_warning": False, "direction": "NONE",
                    "consecutive": 0, "acceleration": 0.0, "vol_growing": False}
    _expand_off = {"expanding": False, "ratio": 1.0, "squeeze_break": False, "atr_trending_up": False}
    ema_base = {"ema9": price * 1.001, "ema21": price, "ema_gap_pct": 0.12}
    return {
        "price": price,
        "squeeze_1m":  {"squeeze": sq1_squeeze,  "bb_width": 0.5, "bb_width_pctile": 20 if sq1_squeeze else 60, "price_position": sq1_pos},
        "squeeze_5m":  {"squeeze": sq5_squeeze,  "bb_width": 0.5, "bb_width_pctile": 20 if sq5_squeeze else 60, "price_position": sq5_pos},
        "squeeze_15m": {"squeeze": sq15_squeeze, "bb_width": 0.5, "bb_width_pctile": 20 if sq15_squeeze else 60, "price_position": sq15_pos},
        "rsi_div_1m": {"divergence": rsi_div_1m, "rsi": rsi_1m},
        "rsi_div_5m": {"divergence": rsi_div_5m, "rsi": rsi_5m},
        "vol_spike_1m": {"vol_spike": vol_spike, "vol_ratio": vol_ratio, "price_move_ratio": price_move_ratio, "candle_dir": candle_dir, "atr": atr},
        "vol_spike_5m": {"vol_spike": False, "vol_ratio": 1.0, "price_move_ratio": 0.5, "candle_dir": "LONG", "atr": atr},
        "vol_spike_15m": {"vol_spike": False, "vol_ratio": 1.0, "price_move_ratio": 0.5, "candle_dir": "LONG", "atr": atr},
        "macd_pre_1m": {"pre_cross": macd_1m, "macd_hist": 0.1, "convergence_rate": 0.3},
        "macd_pre_5m": {"pre_cross": macd_5m, "macd_hist": 0.1, "convergence_rate": 0.3},
        "ema_1m":  {"ema_bullish": ema_1m_bull,  **ema_base},
        "ema_5m":  {"ema_bullish": ema_5m_bull,  **ema_base},
        "ema_15m": {"ema_bullish": ema_15m_bull, **ema_base},
        "cascade_1m":    cascade_1m   or _cascade_off,
        "cascade_5m":    cascade_5m   or _cascade_off,
        "vol_expand_1m": vol_expand_1m or _expand_off,
        "vol_expand_5m": vol_expand_5m or _expand_off,
        "atr_15m": atr,
    }


def trace_evaluate(symbol, ind):
    """Reproduce la lógica de signals.evaluate() paso a paso, mostrando cada filtro."""
    long_score = 0
    short_score = 0
    total_signals = 0
    reasons = []

    print(f"\n  --- Paso 1: SQUEEZE ---")
    for tf, key, weight, bull_thr, bear_thr in [
        ("1m", "squeeze_1m", 1, 0.7, 0.3),
        ("5m", "squeeze_5m", 1, 0.7, 0.3),
        ("15m", "squeeze_15m", 2, 0.6, 0.4),
    ]:
        sq = ind[key]
        if sq["squeeze"]:
            total_signals += 1
            pos = sq["price_position"]
            if pos > bull_thr:
                long_score += weight
                reasons.append(f"Squeeze {tf} → LONG +{weight}")
                print(f"    ✅ Squeeze {tf}: pos={pos:.2f} > {bull_thr} → LONG +{weight}")
            elif pos < bear_thr:
                short_score += weight
                reasons.append(f"Squeeze {tf} → SHORT +{weight}")
                print(f"    ✅ Squeeze {tf}: pos={pos:.2f} < {bear_thr} → SHORT +{weight}")
            else:
                print(f"    ⚠️  Squeeze {tf}: pos={pos:.2f} entre {bear_thr}-{bull_thr} → NO puntúa pero total_signals+1 (DILUYE confianza)")
        else:
            print(f"    ❌ Squeeze {tf}: no activo")

    breakout_imminent = ind["squeeze_1m"]["squeeze"] or ind["squeeze_5m"]["squeeze"]
    print(f"    → breakout_imminent = {breakout_imminent}")

    print(f"\n  --- Paso 2: DIVERGENCIA RSI ---")
    for tf, key, weight in [("1m", "rsi_div_1m", 1), ("5m", "rsi_div_5m", 2)]:
        div = ind[key]
        if div["divergence"] == "BULL":
            long_score += weight
            total_signals += 1
            print(f"    ✅ Divergencia {tf}: BULL (RSI={div['rsi']:.0f}) → LONG +{weight}")
        elif div["divergence"] == "BEAR":
            short_score += weight
            total_signals += 1
            print(f"    ✅ Divergencia {tf}: BEAR (RSI={div['rsi']:.0f}) → SHORT +{weight}")
        else:
            print(f"    ❌ Divergencia {tf}: ninguna (RSI={div['rsi']:.0f})")

    rsi = ind["rsi_div_1m"]["rsi"]
    if rsi > 75:
        short_score += 1
        total_signals += 1
        print(f"    ✅ RSI extremo: {rsi:.0f} > 75 → SHORT +1")
    elif rsi < 25:
        long_score += 1
        total_signals += 1
        print(f"    ✅ RSI extremo: {rsi:.0f} < 25 → LONG +1")
    else:
        print(f"    ❌ RSI normal: {rsi:.0f} (no es extremo)")

    print(f"\n  --- Paso 3: VOLUMEN ---")
    vol = ind["vol_spike_1m"]
    if vol["vol_spike"]:
        total_signals += 1
        if vol["candle_dir"] == "LONG":
            long_score += 2
            print(f"    ✅ Vol spike: ratio={vol['vol_ratio']:.1f}x dir=LONG → LONG +2")
        else:
            short_score += 2
            print(f"    ✅ Vol spike: ratio={vol['vol_ratio']:.1f}x dir=SHORT → SHORT +2")
    else:
        print(f"    ❌ Sin spike de volumen (ratio={vol['vol_ratio']:.1f}x)")

    print(f"\n  --- Paso 4: MACD PRE-CRUCE ---")
    for tf, key, weight in [("1m", "macd_pre_1m", 1), ("5m", "macd_pre_5m", 2)]:
        m = ind[key]
        if m["pre_cross"] == "LONG":
            long_score += weight
            total_signals += 1
            print(f"    ✅ MACD {tf}: pre-cruce LONG → LONG +{weight}")
        elif m["pre_cross"] == "SHORT":
            short_score += weight
            total_signals += 1
            print(f"    ✅ MACD {tf}: pre-cruce SHORT → SHORT +{weight}")
        else:
            print(f"    ❌ MACD {tf}: sin pre-cruce")

    print(f"\n  --- Paso 5: EMA MULTI-TF ---")
    all_bull = ind["ema_1m"]["ema_bullish"] and ind["ema_5m"]["ema_bullish"] and ind["ema_15m"]["ema_bullish"]
    all_bear = not ind["ema_1m"]["ema_bullish"] and not ind["ema_5m"]["ema_bullish"] and not ind["ema_15m"]["ema_bullish"]
    if all_bull:
        long_score += 2
        total_signals += 1
        print(f"    ✅ EMA 1m+5m+15m todas alcistas → LONG +2")
    elif all_bear:
        short_score += 2
        total_signals += 1
        print(f"    ✅ EMA 1m+5m+15m todas bajistas → SHORT +2")
    else:
        print(f"    ❌ EMAs no alineadas (1m={ind['ema_1m']['ema_bullish']}, 5m={ind['ema_5m']['ema_bullish']}, 15m={ind['ema_15m']['ema_bullish']})")

    # --- FILTROS ---
    max_score = max(long_score, short_score)
    total_possible = total_signals * 2
    confidence = min(max_score / max(total_possible, 1) * 100, 99)
    direction = "LONG" if long_score >= short_score else "SHORT"

    atr = vol["atr"]
    price = ind["price"]
    multiplier = 1 + (max_score / 10)
    expected_move = atr * multiplier
    move_pct = expected_move / price * 100

    print(f"\n  {'='*50}")
    print(f"  PUNTUACIÓN FINAL:")
    print(f"    long_score  = {long_score}")
    print(f"    short_score = {short_score}")
    print(f"    max_score   = {max_score}")
    print(f"    total_signals    = {total_signals}")
    print(f"    total_possible   = {total_possible} (total_signals × 2)")
    print(f"    confianza        = {max_score}/{total_possible} × 100 = {confidence:.1f}%")
    print(f"    dirección        = {direction}")
    print(f"    ATR              = ${atr:.2f}")
    print(f"    mov. esperado    = {move_pct:.4f}%")
    print(f"  {'='*50}")

    print(f"\n  --- FILTROS (deben pasar TODOS) ---")
    passed = True

    # Filtro 1: gate breakout/volumen
    if not breakout_imminent and not vol["vol_spike"]:
        if max_score < 5:
            print(f"    ❌ FILTRO 1: Sin breakout ni vol_spike → necesita score≥5, tiene {max_score}")
            passed = False
        else:
            print(f"    ✅ FILTRO 1: Sin breakout/vol pero score={max_score}≥5")
    else:
        trigger = []
        if breakout_imminent: trigger.append("squeeze")
        if vol["vol_spike"]: trigger.append("vol_spike")
        print(f"    ✅ FILTRO 1: Tiene {'+'.join(trigger)} → gate abierto")

    # Filtro 2: score mínimo
    if max_score < 3:
        print(f"    ❌ FILTRO 2: score={max_score} < 3 mínimo")
        passed = False
    else:
        print(f"    ✅ FILTRO 2: score={max_score} ≥ 3")

    # Filtro 3: confianza
    if confidence < signals.MIN_CONFIDENCE:
        print(f"    ❌ FILTRO 3: confianza={confidence:.1f}% < {signals.MIN_CONFIDENCE}% mínimo")
        passed = False
    else:
        print(f"    ✅ FILTRO 3: confianza={confidence:.1f}% ≥ {signals.MIN_CONFIDENCE}%")

    # Filtro 4: movimiento
    if move_pct < signals.MIN_MOVE_PCT:
        print(f"    ❌ FILTRO 4: mov={move_pct:.4f}% < {signals.MIN_MOVE_PCT}% mínimo")
        passed = False
    else:
        print(f"    ✅ FILTRO 4: mov={move_pct:.4f}% ≥ {signals.MIN_MOVE_PCT}%")

    # Filtro 5: cooldown
    print(f"    ✅ FILTRO 5: cooldown OK (state reseteado)")

    if passed:
        print(f"\n  🚀 SEÑAL ENVIADA: {direction} {confidence:.0f}% mov={move_pct:+.2f}%")
    else:
        print(f"\n  🔇 SIN SEÑAL (bloqueado por filtros)")

    return passed


def reset_cooldown():
    """Resetea el cooldown entre escenarios."""
    with open(STATE_FILE, "w") as f:
        json.dump({}, f)


# =============================================================================
#  ESCENARIOS DE TEST
# =============================================================================

print("=" * 70)
print("  SIMULACIÓN DE SEÑALES — Escenarios con datos controlados")
print("=" * 70)

# ── ESCENARIO 1: Mercado aburrido (lo más común) ────────────────────────
print(f"\n{'━'*70}")
print("  ESCENARIO 1: Mercado lateral / sin acción")
print(f"{'━'*70}")
print("  Situación: BTC en $85,000, sin squeeze, sin divergencias, sin spikes.")
print("  Esto es lo que pasa el 90% del tiempo.")

ind1 = make_indicators()
trace_evaluate("BTC/USDT", ind1)

# ── ESCENARIO 2: Squeeze activo pero precio en zona muerta ──────────────
print(f"\n{'━'*70}")
print("  ESCENARIO 2: Squeeze activo pero precio en ZONA MUERTA")
print(f"{'━'*70}")
print("  Situación: Las bandas se comprimieron (breakout viene) pero el precio")
print("  está en el medio de las bandas. El bot no sabe si irá arriba o abajo.")

ind2 = make_indicators(
    sq1_squeeze=True, sq1_pos=0.50,   # squeeze activo, precio en medio
    sq5_squeeze=True, sq5_pos=0.45,   # idem en 5m
    macd_1m="LONG",                   # MACD dice long
    ema_1m_bull=True, ema_5m_bull=True, ema_15m_bull=True,  # EMAs alineadas
    atr=300.0,
)
reset_cooldown()
trace_evaluate("BTC/USDT", ind2)

# ── ESCENARIO 3: ✅ SEÑAL LONG — Todo alineado ─────────────────────────
print(f"\n{'━'*70}")
print("  ESCENARIO 3: ✅ SEÑAL LONG — Condiciones ideales")
print(f"{'━'*70}")
print("  Situación: BTC en $85,000. Squeeze en 1m con precio cerca de banda")
print("  superior, divergencia alcista en 5m, MACD convergiendo a cruce alcista,")
print("  todas las EMAs alcistas, y ATR alto (mercado volátil).")
print("  → Este es el caso donde SÍ se envía la señal.")

ind3 = make_indicators(
    sq1_squeeze=True, sq1_pos=0.85,   # squeeze 1m, precio arriba → LONG +1
    rsi_div_5m="BULL", rsi_5m=38.0,   # divergencia alcista 5m → LONG +2
    macd_5m="LONG",                   # MACD 5m cruce inminente → LONG +2
    ema_1m_bull=True, ema_5m_bull=True, ema_15m_bull=True,  # EMAs → LONG +2
    atr=500.0,                        # ATR alto → mov. grande
)
reset_cooldown()
result3 = trace_evaluate("BTC/USDT", ind3)

# Verificar con la función real
reset_cooldown()
real3 = signals.evaluate("BTC/USDT", ind3)
print(f"\n  📋 Verificación con signals.evaluate() real:")
if real3:
    print(f"    → {real3['direction']} confianza={real3['confidence']:.0f}% mov={real3['move_pct']:+.2f}%")
    print(f"    → Entrada: ${real3['trade']['entry']:,.2f}  Target: ${real3['trade']['target']:,.2f}  Stop: ${real3['trade']['stop']:,.2f}")
    print(f"    → PnL esperado: +${real3['trade']['expected_pnl']:,.2f}  Riesgo: -${real3['trade']['risk_pnl']:,.2f}")
else:
    print(f"    → None (no se generó señal)")

# ── ESCENARIO 4: ✅ SEÑAL SHORT — Caída inminente ──────────────────────
print(f"\n{'━'*70}")
print("  ESCENARIO 4: ✅ SEÑAL SHORT — Caída inminente")
print(f"{'━'*70}")
print("  Situación: ETH en $3,200. Volumen anómalo 2.5x con vela bajista")
print("  (distribución), divergencia bajista en 5m, MACD cruzando a negativo,")
print("  todas las EMAs bajistas.")

ind4 = make_indicators(
    price=3200.0,
    vol_spike=True, vol_ratio=2.5, candle_dir="SHORT",   # vol spike → SHORT +2
    rsi_div_5m="BEAR", rsi_5m=68.0,                       # div bajista 5m → SHORT +2
    macd_1m="SHORT",                                       # MACD 1m → SHORT +1
    ema_1m_bull=False, ema_5m_bull=False, ema_15m_bull=False,  # EMAs → SHORT +2
    atr=25.0,                                              # ATR para ETH
)
reset_cooldown()
result4 = trace_evaluate("ETH/USDT", ind4)

reset_cooldown()
real4 = signals.evaluate("ETH/USDT", ind4)
print(f"\n  📋 Verificación con signals.evaluate() real:")
if real4:
    print(f"    → {real4['direction']} confianza={real4['confidence']:.0f}% mov={real4['move_pct']:+.2f}%")
    print(f"    → Entrada: ${real4['trade']['entry']:,.2f}  Target: ${real4['trade']['target']:,.2f}  Stop: ${real4['trade']['stop']:,.2f}")
else:
    print(f"    → None")

# ── ESCENARIO 5: Casi pasa pero confianza insuficiente ──────────────────
print(f"\n{'━'*70}")
print("  ESCENARIO 5: Casi pasa — Muchas señales pero diluidas")
print(f"{'━'*70}")
print("  Situación: Hay squeeze en 1m Y 5m (ambos en zona muerta), más MACD")
print("  y EMA alineadas. Muchas señales activas pero sin puntuar → confianza baja.")

ind5 = make_indicators(
    sq1_squeeze=True, sq1_pos=0.55,    # squeeze pero zona muerta → no puntúa
    sq5_squeeze=True, sq5_pos=0.48,    # idem → no puntúa
    rsi_div_1m="BULL", rsi_1m=42.0,    # div alcista 1m → LONG +1
    macd_1m="LONG",                    # MACD 1m → LONG +1
    ema_1m_bull=True, ema_5m_bull=True, ema_15m_bull=True,  # EMAs → LONG +2
    atr=400.0,
)
reset_cooldown()
trace_evaluate("BTC/USDT", ind5)

# ── ESCENARIO 6: Señal por score alto sin breakout ──────────────────────
print(f"\n{'━'*70}")
print("  ESCENARIO 6: Sin squeeze ni spike pero score aplastante (≥5)")
print(f"{'━'*70}")
print("  Situación: No hay squeeze ni volumen anómalo, pero TODOS los demás")
print("  indicadores apuntan SHORT con fuerza. ¿Pasa el gate?")

ind6 = make_indicators(
    price=85000.0,
    rsi_div_1m="BEAR", rsi_1m=78.0,    # div bajista + RSI sobrecompra → SHORT +1+1
    rsi_div_5m="BEAR", rsi_5m=72.0,    # div bajista 5m → SHORT +2
    macd_5m="SHORT",                    # MACD 5m → SHORT +2
    ema_1m_bull=False, ema_5m_bull=False, ema_15m_bull=False,  # EMAs → SHORT +2
    atr=500.0,
)
reset_cooldown()
trace_evaluate("BTC/USDT", ind6)

# ── RESUMEN ──────────────────────────────────────────────────────────────
print(f"\n{'━'*70}")
print("  RESUMEN: ¿Cuándo recibirías la señal?")
print(f"{'━'*70}")
print("""
  Para recibir una señal, necesitas que se cumplan TODAS estas condiciones
  simultáneamente:

  1. GATE DE ENTRADA (al menos uno):
     a) Squeeze de Bollinger en 1m ó 5m (bandas comprimidas)
     b) Pico de volumen anómalo (>1.5x media con precio quieto)
     c) Score ≥ 5 sin ninguno de los anteriores (muy difícil)

  2. DIRECCIÓN CLARA: el precio debe estar en los EXTREMOS de las bandas
     durante el squeeze (>0.7 para LONG, <0.3 para SHORT), NO en el medio.

  3. SCORE ≥ 3: al menos 3 puntos en una dirección.

  4. CONFIANZA ≥ 60%: score / (total_señales_activas × 2) × 100.
     ⚠️  Señales que no puntúan BAJAN la confianza.

  5. MOVIMIENTO ≥ 0.3%: depende del ATR. En mercados tranquilos, el ATR
     es bajo y el movimiento esperado no llega al 0.3%.

  6. COOLDOWN: no haber alertado el mismo par+dirección en los últimos 5 min.

  → En la práctica: necesitas un mercado VOLÁTIL con VARIAS señales técnicas
    alineadas en la misma dirección. En mercado lateral/tranquilo (como suele
    estar BTC en horarios de baja actividad), es casi imposible que se alineen.
""")
