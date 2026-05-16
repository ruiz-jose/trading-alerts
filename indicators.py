import numpy as np
import pandas as pd
import pandas_ta as ta


def _bollinger_squeeze(df: pd.DataFrame) -> dict:
    """Detecta compresión de Bollinger Bands (squeeze) = breakout inminente.

    Cuando el ancho de las bandas es el menor de las últimas 20 velas,
    el precio está acumulando energía para un movimiento fuerte.
    """
    bb = ta.bbands(df["close"], length=20, std=2)
    if bb is None or bb.empty:
        return {"squeeze": False, "bb_width": 0, "bb_width_pctile": 50, "price_position": 0.5}

    upper_col = [c for c in bb.columns if "BBU" in c][0]
    lower_col = [c for c in bb.columns if "BBL" in c][0]
    mid_col = [c for c in bb.columns if "BBM" in c][0]

    width = bb[upper_col] - bb[lower_col]
    width_pct = width / bb[mid_col] * 100

    curr_width = width_pct.iloc[-1]
    # Percentil del ancho actual vs últimas 50 velas
    recent = width_pct.tail(50).dropna()
    pctile = (recent < curr_width).sum() / len(recent) * 100 if len(recent) > 0 else 50

    # Posición del precio dentro de las bandas (0=lower, 1=upper)
    price = df["close"].iloc[-1]
    bb_range = bb[upper_col].iloc[-1] - bb[lower_col].iloc[-1]
    price_pos = (price - bb[lower_col].iloc[-1]) / bb_range if bb_range > 0 else 0.5

    return {
        "squeeze": pctile < 40,  # ancho en el 40% más bajo = squeeze
        "bb_width": curr_width,
        "bb_width_pctile": pctile,
        "price_position": price_pos,  # >0.8 = tocando upper, <0.2 = tocando lower
    }


def _rsi_divergence(df: pd.DataFrame) -> dict:
    """Detecta divergencia RSI/precio = reversión inminente.

    Divergencia alcista: precio hace mínimos más bajos, RSI hace mínimos más altos.
    Divergencia bajista: precio hace máximos más altos, RSI hace máximos más bajos.
    """
    df = df.copy()
    df["rsi"] = ta.rsi(df["close"], length=14)
    rsi = df["rsi"].dropna()

    if len(rsi) < 20:
        return {"divergence": "NONE", "rsi": rsi.iloc[-1] if len(rsi) > 0 else 50}

    rsi_val = rsi.iloc[-1]

    # Comparar últimos 2 valles/picos en ventanas de 10 velas
    close_recent = df["close"].tail(20)
    rsi_recent = rsi.tail(20)

    # Divergencia alcista (señal de SUBIDA)
    price_low1 = close_recent.iloc[:10].min()
    price_low2 = close_recent.iloc[10:].min()
    rsi_low1 = rsi_recent.iloc[:10].min()
    rsi_low2 = rsi_recent.iloc[10:].min()

    bull_div = price_low2 < price_low1 and rsi_low2 > rsi_low1

    # Divergencia bajista (señal de CAÍDA)
    price_high1 = close_recent.iloc[:10].max()
    price_high2 = close_recent.iloc[10:].max()
    rsi_high1 = rsi_recent.iloc[:10].max()
    rsi_high2 = rsi_recent.iloc[10:].max()

    bear_div = price_high2 > price_high1 and rsi_high2 < rsi_high1

    div = "BULL" if bull_div else "BEAR" if bear_div else "NONE"
    return {"divergence": div, "rsi": rsi_val}


def _volume_spike(df: pd.DataFrame) -> dict:
    """Detecta pico de volumen anómalo sin movimiento proporcional de precio.

    Volumen alto + precio quieto = acumulación/distribución = movimiento inminente.
    """
    vol = df["volume"]
    vol_mean = vol.rolling(20).mean().iloc[-1]
    vol_curr = vol.iloc[-1]
    vol_ratio = vol_curr / vol_mean if vol_mean > 0 else 0

    # Movimiento de precio en la última vela
    price_change = abs(df["close"].iloc[-1] - df["open"].iloc[-1])
    atr = ta.atr(df["high"], df["low"], df["close"], length=14)
    atr_val = atr.iloc[-1] if atr is not None and not atr.empty else price_change

    price_move_ratio = price_change / atr_val if atr_val > 0 else 0

    # Pico = volumen > 1.5x media PERO precio se movió < 0.7 ATR
    spike = vol_ratio > 1.5 and price_move_ratio < 0.7

    # Dirección sugerida por la vela
    candle_dir = "LONG" if df["close"].iloc[-1] >= df["open"].iloc[-1] else "SHORT"

    return {
        "vol_spike": spike,
        "vol_ratio": vol_ratio,
        "price_move_ratio": price_move_ratio,
        "candle_dir": candle_dir,
        "atr": atr_val,
    }


_MACD_FAST, _MACD_SLOW, _MACD_SIGNAL = 12, 26, 9
_MACD_COL = f"MACD_{_MACD_FAST}_{_MACD_SLOW}_{_MACD_SIGNAL}"
_MACD_HIST_COL = f"MACDh_{_MACD_FAST}_{_MACD_SLOW}_{_MACD_SIGNAL}"
_MACD_SIG_COL = f"MACDs_{_MACD_FAST}_{_MACD_SLOW}_{_MACD_SIGNAL}"


def _macd_pre_cross(df: pd.DataFrame) -> dict:
    """Detecta cruce de MACD inminente (MACD y Signal convergen).

    Si la distancia entre MACD y Signal se reduce en las últimas 3 velas,
    un cruce está por ocurrir.
    """
    macd_df = ta.macd(df["close"], fast=_MACD_FAST, slow=_MACD_SLOW, signal=_MACD_SIGNAL)
    if macd_df is None or macd_df.empty or _MACD_HIST_COL not in macd_df.columns:
        return {"pre_cross": "NONE", "macd_hist": 0, "convergence_rate": 0}

    hist = macd_df[_MACD_HIST_COL]
    hist_vals = hist.tail(5).dropna()

    if len(hist_vals) < 3:
        return {"pre_cross": "NONE", "macd_hist": 0, "convergence_rate": 0}

    hist_curr = hist_vals.iloc[-1]
    hist_prev = hist_vals.iloc[-2]
    hist_prev2 = hist_vals.iloc[-3]

    # Convergencia: el histograma se acerca a 0
    dist_curr = abs(hist_curr)
    dist_prev = abs(hist_prev)
    dist_prev2 = abs(hist_prev2)

    converging = dist_curr < dist_prev < dist_prev2
    convergence_rate = (dist_prev - dist_curr) / dist_prev if dist_prev > 0 else 0

    if converging and convergence_rate > 0.1:
        # El hist se acerca a 0 → cruce inminente
        if hist_curr > 0:
            pre_cross = "SHORT"  # va a cruzar a negativo
        else:
            pre_cross = "LONG"   # va a cruzar a positivo
    else:
        pre_cross = "NONE"

    return {
        "pre_cross": pre_cross,
        "macd_hist": hist_curr,
        "convergence_rate": convergence_rate,
    }


def _momentum_cascade(df: pd.DataFrame) -> dict:
    """Detecta acumulación de momentum = movimiento grande INMINENTE.

    Señales predictivas:
    1. 3+ velas consecutivas en la misma dirección
    2. Cuerpos de velas crecientes (aceleración)
    3. Volumen creciente en cada vela (presión aumentando)

    Estadísticamente, cuando hay 3+ velas consecutivas con cuerpos
    crecientes y volumen creciente, hay ~70% de probabilidad de que
    la siguiente vela sea aún más grande en la misma dirección.
    """
    if len(df) < 6:
        return {"cascade": False, "direction": "NONE", "consecutive": 0,
                "acceleration": 0.0, "vol_growing": False}

    closes = df["close"].values
    opens = df["open"].values
    volumes = df["volume"].values

    # Analizar últimas 5 velas para detectar cascada formándose
    bodies = []
    directions = []
    vols = []
    for i in range(-5, 0):
        body = closes[i] - opens[i]
        bodies.append(body)
        directions.append(1 if body > 0 else -1 if body < 0 else 0)
        vols.append(volumes[i])

    # Contar velas consecutivas en misma dirección (desde la más reciente)
    last_dir = directions[-1]
    consecutive = 0
    for d in reversed(directions):
        if d == last_dir and d != 0:
            consecutive += 1
        else:
            break

    if consecutive < 2:
        return {"cascade": False, "direction": "NONE", "consecutive": 0,
                "acceleration": 0.0, "vol_growing": False}

    # Verificar aceleración: cuerpos crecientes
    recent_bodies = [abs(b) for b in bodies[-consecutive:]]
    body_growing = all(
        recent_bodies[i] >= recent_bodies[i - 1] * 0.9
        for i in range(1, len(recent_bodies))
    )

    # Verificar volumen creciente
    recent_vols = vols[-consecutive:]
    vol_growing = all(
        recent_vols[i] >= recent_vols[i - 1] * 0.85
        for i in range(1, len(recent_vols))
    )

    # Tasa de aceleración: cuánto creció el último cuerpo vs el primero
    if recent_bodies[0] > 0:
        acceleration = recent_bodies[-1] / recent_bodies[0]
    else:
        acceleration = 0.0

    # Cascada = 3+ velas consecutivas con cuerpos que no decrecen + volumen sostenido
    cascade = consecutive >= 3 and body_growing and vol_growing

    # Cascada parcial = 2 velas con fuerte aceleración (precursor temprano)
    early_warning = (consecutive >= 2 and acceleration >= 1.5
                     and vol_growing and not cascade)

    direction = "LONG" if last_dir > 0 else "SHORT"

    return {
        "cascade": cascade,
        "early_warning": early_warning,
        "direction": direction,
        "consecutive": consecutive,
        "acceleration": acceleration,
        "vol_growing": vol_growing,
    }


def _volatility_expansion(df: pd.DataFrame) -> dict:
    """Detecta expansión rápida de volatilidad = movimiento explosivo inminente.

    Compara ATR reciente (últimas 5 velas) vs ATR histórico (últimas 20).
    Cuando la volatilidad reciente es >1.5x la histórica, un movimiento
    grande está en desarrollo y probablemente continuará.

    También detecta 'volatility squeeze → expansion': si el ATR estuvo
    comprimido y ahora se expande, es el inicio de un movimiento fuerte.
    """
    atr = ta.atr(df["high"], df["low"], df["close"], length=14)
    if atr is None or len(atr.dropna()) < 20:
        return {"expanding": False, "ratio": 1.0, "squeeze_break": False}

    atr_clean = atr.dropna()

    # ATR promedio reciente (5 velas) vs histórico (20 velas)
    atr_recent = atr_clean.tail(5).mean()
    atr_hist = atr_clean.tail(20).mean()
    ratio = atr_recent / atr_hist if atr_hist > 0 else 1.0

    # ATR de la penúltima ventana (para detectar squeeze → expansion)
    atr_prev_5 = atr_clean.iloc[-10:-5].mean() if len(atr_clean) >= 10 else atr_hist
    was_compressed = atr_prev_5 < atr_hist * 0.75
    squeeze_break = was_compressed and ratio > 1.3

    # Tendencia del ATR: ¿cada vela es más volátil que la anterior?
    last_5_atr = atr_clean.tail(5).values
    atr_trending_up = all(
        last_5_atr[i] >= last_5_atr[i - 1] * 0.95
        for i in range(1, len(last_5_atr))
    )

    expanding = (ratio > 1.5 and atr_trending_up) or squeeze_break

    return {
        "expanding": expanding,
        "ratio": ratio,
        "squeeze_break": squeeze_break,
        "atr_trending_up": atr_trending_up,
    }


def _ema_trend(df: pd.DataFrame) -> dict:
    """EMA 9/21 para confirmar tendencia de fondo."""
    ema9 = ta.ema(df["close"], length=9)
    ema21 = ta.ema(df["close"], length=21)

    if ema9 is None or ema21 is None:
        return {"ema_bullish": False, "ema9": 0, "ema21": 0, "ema_gap_pct": 0}

    e9 = ema9.iloc[-1]
    e21 = ema21.iloc[-1]
    gap_pct = (e9 - e21) / e21 * 100 if e21 > 0 else 0

    return {
        "ema_bullish": e9 > e21,
        "ema9": e9,
        "ema21": e21,
        "ema_gap_pct": gap_pct,
    }


def compute(frames: dict[str, pd.DataFrame], live_price: float) -> dict:
    """Analiza múltiples timeframes y detecta patrones PRE-BREAKOUT.

    frames: {"1m": df, "5m": df, "15m": df}
    Retorna un dict con todos los indicadores predictivos.
    """
    df_1m = frames["1m"].copy()
    df_5m = frames["5m"].copy()
    df_15m = frames["15m"].copy()

    # Inyectar precio en vivo en la última vela de 1m
    df_1m.iloc[-1, df_1m.columns.get_loc("close")] = live_price

    # --- Indicadores predictivos en 1m (reacción rápida) ---
    squeeze_1m = _bollinger_squeeze(df_1m)
    rsi_div_1m = _rsi_divergence(df_1m)
    vol_spike_1m = _volume_spike(df_1m)
    macd_pre_1m = _macd_pre_cross(df_1m)
    ema_1m = _ema_trend(df_1m)

    # --- Confirmación en 5m (tendencia intermedia) ---
    squeeze_5m = _bollinger_squeeze(df_5m)
    rsi_div_5m = _rsi_divergence(df_5m)
    vol_spike_5m = _volume_spike(df_5m)
    ema_5m = _ema_trend(df_5m)
    macd_pre_5m = _macd_pre_cross(df_5m)

    # --- Contexto en 15m (tendencia macro) ---
    ema_15m = _ema_trend(df_15m)
    squeeze_15m = _bollinger_squeeze(df_15m)
    vol_spike_15m = _volume_spike(df_15m)

    # --- Movimiento brusco predictivo ---
    cascade_1m = _momentum_cascade(df_1m)
    cascade_5m = _momentum_cascade(df_5m)
    vol_expand_1m = _volatility_expansion(df_1m)
    vol_expand_5m = _volatility_expansion(df_5m)

    return {
        "price": live_price,
        # 1m
        "squeeze_1m": squeeze_1m,
        "rsi_div_1m": rsi_div_1m,
        "vol_spike_1m": vol_spike_1m,
        "macd_pre_1m": macd_pre_1m,
        "ema_1m": ema_1m,
        # 5m
        "squeeze_5m": squeeze_5m,
        "rsi_div_5m": rsi_div_5m,
        "vol_spike_5m": vol_spike_5m,
        "ema_5m": ema_5m,
        "macd_pre_5m": macd_pre_5m,
        # 15m
        "ema_15m": ema_15m,
        "squeeze_15m": squeeze_15m,
        "vol_spike_15m": vol_spike_15m,
        # ATR de 15m para estimar movimiento real
        "atr_15m": vol_spike_15m["atr"],
        # Predictivos: cascada de momentum + expansión de volatilidad
        "cascade_1m": cascade_1m,
        "cascade_5m": cascade_5m,
        "vol_expand_1m": vol_expand_1m,
        "vol_expand_5m": vol_expand_5m,
    }


def compute_bmsb(df_1w: pd.DataFrame, live_price: float | None = None) -> dict | None:
    """Calcula el Bull Market Support Band en timeframe semanal.

    Bandas:
        SMA 20 semanas  +  EMA 21 semanas

    Zonas:
        BULL    — precio por encima de AMBAS bandas
        BEAR    — precio por debajo de AMBAS bandas
        NEUTRAL — precio entre las dos bandas

    Usa la última vela semanal CERRADA (iloc[-2]) para los valores de las
    bandas, evitando señales falsas de la vela en curso.
    El precio evaluado es live_price si se provee, o el cierre de la última
    vela cerrada si no.
    """
    if len(df_1w) < 25:
        return None

    sma20 = ta.sma(df_1w["close"], length=20)
    ema21 = ta.ema(df_1w["close"], length=21)

    if sma20 is None or ema21 is None:
        return None

    clean_sma = sma20.dropna()
    clean_ema = ema21.dropna()
    if len(clean_sma) < 2 or len(clean_ema) < 2:
        return None

    # Última vela cerrada para las bandas (iloc[-2] = penúltima = ya confirmada)
    sma20_val = sma20.iloc[-2]
    ema21_val = ema21.iloc[-2]
    price = live_price if live_price is not None else df_1w["close"].iloc[-2]

    # Zona actual
    above_both = price > sma20_val and price > ema21_val
    below_both = price < sma20_val and price < ema21_val
    zone = "BULL" if above_both else "BEAR" if below_both else "NEUTRAL"

    # Distancia porcentual a cada banda (positivo = precio por encima)
    dist_sma20_pct = (price - sma20_val) / sma20_val * 100
    dist_ema21_pct = (price - ema21_val) / ema21_val * 100

    return {
        "sma20": sma20_val,
        "ema21": ema21_val,
        "price": price,
        "zone": zone,
        "above_both": above_both,
        "below_both": below_both,
        "dist_sma20_pct": dist_sma20_pct,
        "dist_ema21_pct": dist_ema21_pct,
    }
