"""Diagnóstico: muestra TODOS los indicadores para entender por qué no alerta."""
import data
import indicators

info = data.fetch_all()
for sym, d in info.items():
    ind = indicators.compute(d["frames"], live_price=d["price"])
    print(f"\n{'='*60}")
    print(f"  {sym} — Precio: ${ind['price']:,.2f}")
    print(f"{'='*60}")

    sq1 = ind["squeeze_1m"]
    sq5 = ind["squeeze_5m"]
    sq15 = ind["squeeze_15m"]
    print(f"\n  BOLLINGER SQUEEZE:")
    print(f"    1m:  squeeze={sq1['squeeze']}  ancho_pctile={sq1['bb_width_pctile']:.0f}%  pos_precio={sq1['price_position']:.2f}")
    print(f"    5m:  squeeze={sq5['squeeze']}  ancho_pctile={sq5['bb_width_pctile']:.0f}%  pos_precio={sq5['price_position']:.2f}")
    print(f"    15m: squeeze={sq15['squeeze']}  ancho_pctile={sq15['bb_width_pctile']:.0f}%  pos_precio={sq15['price_position']:.2f}")

    div1 = ind["rsi_div_1m"]
    div5 = ind["rsi_div_5m"]
    print(f"\n  DIVERGENCIA RSI:")
    print(f"    1m:  divergencia={div1['divergence']}  RSI={div1['rsi']:.1f}")
    print(f"    5m:  divergencia={div5['divergence']}  RSI={div5['rsi']:.1f}")

    vol = ind["vol_spike_1m"]
    print(f"\n  VOLUMEN:")
    print(f"    spike={vol['vol_spike']}  ratio={vol['vol_ratio']:.2f}x  precio_move={vol['price_move_ratio']:.2f}  dir={vol['candle_dir']}  ATR=${vol['atr']:.2f}")

    m1 = ind["macd_pre_1m"]
    m5 = ind["macd_pre_5m"]
    print(f"\n  MACD PRE-CRUCE:")
    print(f"    1m:  pre_cross={m1['pre_cross']}  hist={m1['macd_hist']:.4f}  convergencia={m1['convergence_rate']:.2f}")
    print(f"    5m:  pre_cross={m5['pre_cross']}  hist={m5['macd_hist']:.4f}  convergencia={m5['convergence_rate']:.2f}")

    e1 = ind["ema_1m"]
    e5 = ind["ema_5m"]
    e15 = ind["ema_15m"]
    print(f"\n  EMA TENDENCIA:")
    print(f"    1m:  bull={e1['ema_bullish']}  gap={e1['ema_gap_pct']:.4f}%")
    print(f"    5m:  bull={e5['ema_bullish']}  gap={e5['ema_gap_pct']:.4f}%")
    print(f"    15m: bull={e15['ema_bullish']}  gap={e15['ema_gap_pct']:.4f}%")

    # Predictivos
    cas1 = ind.get("cascade_1m", {})
    cas5 = ind.get("cascade_5m", {})
    vex1 = ind.get("vol_expand_1m", {})
    vex5 = ind.get("vol_expand_5m", {})
    print(f"\n  CASCADA DE MOMENTUM (predictivo):")
    print(f"    1m:  cascade={cas1.get('cascade')}  early_warning={cas1.get('early_warning')}  dir={cas1.get('direction')}  consec={cas1.get('consecutive')}  accel={cas1.get('acceleration', 0):.1f}x  vol_growing={cas1.get('vol_growing')}")
    print(f"    5m:  cascade={cas5.get('cascade')}  early_warning={cas5.get('early_warning')}  dir={cas5.get('direction')}  consec={cas5.get('consecutive')}  accel={cas5.get('acceleration', 0):.1f}x  vol_growing={cas5.get('vol_growing')}")
    print(f"\n  EXPANSIÓN DE VOLATILIDAD (predictivo):")
    print(f"    1m:  expanding={vex1.get('expanding')}  ratio={vex1.get('ratio', 0):.2f}x  squeeze_break={vex1.get('squeeze_break')}  atr_trending={vex1.get('atr_trending_up')}")
    print(f"    5m:  expanding={vex5.get('expanding')}  ratio={vex5.get('ratio', 0):.2f}x  squeeze_break={vex5.get('squeeze_break')}  atr_trending={vex5.get('atr_trending_up')}")

    # Simular scoring
    long_s = 0
    short_s = 0
    breakout = sq1["squeeze"] or sq5["squeeze"]
    vol_spike = vol["vol_spike"]

    if sq1["squeeze"]:
        if sq1["price_position"] > 0.7: long_s += 1
        elif sq1["price_position"] < 0.3: short_s += 1
    if sq5["squeeze"]:
        if sq5["price_position"] > 0.7: long_s += 1
        elif sq5["price_position"] < 0.3: short_s += 1
    if sq15["squeeze"]:
        if sq15["price_position"] > 0.6: long_s += 2
        elif sq15["price_position"] < 0.4: short_s += 2
    if div1["divergence"] == "BULL": long_s += 1
    elif div1["divergence"] == "BEAR": short_s += 1
    if div5["divergence"] == "BULL": long_s += 2
    elif div5["divergence"] == "BEAR": short_s += 2
    if vol["vol_spike"]:
        if vol["candle_dir"] == "LONG": long_s += 2
        else: short_s += 2
    if m1["pre_cross"] == "LONG": long_s += 1
    elif m1["pre_cross"] == "SHORT": short_s += 1
    if m5["pre_cross"] == "LONG": long_s += 2
    elif m5["pre_cross"] == "SHORT": short_s += 2
    all_bull = e1["ema_bullish"] and e5["ema_bullish"] and e15["ema_bullish"]
    all_bear = not e1["ema_bullish"] and not e5["ema_bullish"] and not e15["ema_bullish"]
    if all_bull: long_s += 2
    elif all_bear: short_s += 2

    # Predictivos
    predictive = False
    if cas1.get("cascade"):
        predictive = True
        if cas1["direction"] == "LONG": long_s += 3
        else: short_s += 3
    elif cas1.get("early_warning"):
        predictive = True
        if cas1["direction"] == "LONG": long_s += 2
        else: short_s += 2
    if cas5.get("cascade"):
        predictive = True
        if cas5["direction"] == "LONG": long_s += 4
        else: short_s += 4
    elif cas5.get("early_warning"):
        predictive = True
        if cas5["direction"] == "LONG": long_s += 2
        else: short_s += 2
    if vex1.get("expanding"):
        predictive = True
        if e1["ema_bullish"]: long_s += 2
        else: short_s += 2
    if vex5.get("expanding"):
        predictive = True
        if e5["ema_bullish"]: long_s += 2
        else: short_s += 2

    max_s = max(long_s, short_s)
    move_pct = (vol["atr"] * (1 + max_s/10)) / ind["price"] * 100

    print(f"\n  RESULTADO:")
    print(f"    long_score={long_s}  short_score={short_s}  max={max_s}")
    print(f"    breakout_inminente={breakout}  vol_spike={vol_spike}  predictivo={predictive}")
    print(f"    mov_esperado={move_pct:.4f}%  (mínimo=0.3%)")

    # Diagnóstico de por qué falla
    blockers = []
    if not breakout and not vol_spike and not predictive and max_s < 5:
        blockers.append("No hay squeeze NI vol spike NI señal predictiva NI score>=5 → BLOQUEADO por gate")
    if max_s < 3:
        blockers.append(f"Score {max_s} < 3 mínimo")
    if move_pct < 0.3:
        blockers.append(f"Movimiento {move_pct:.4f}% < 0.3% mínimo")

    if blockers:
        print(f"\n  ❌ BLOQUEADORES:")
        for b in blockers:
            print(f"    → {b}")
    else:
        print(f"\n  ✅ PASARÍA LOS FILTROS")
