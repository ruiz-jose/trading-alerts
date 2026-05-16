import logging
import os
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

import web

load_dotenv()

log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def format_message(signal: dict) -> str:
    """Formatea la predicción como mensaje para Telegram con config de Grid Bot."""
    conf = signal["confidence"]
    direction = signal["direction"]

    if direction == "LONG":
        emoji = "🟢"
        texto = "ALCISTA"
        accion = "LONG"
    else:
        emoji = "🔴"
        texto = "BAJISTA"
        accion = "SHORT"

    # Nivel de confianza en palabras
    if conf >= 85:
        nivel = "MUY ALTA"
    elif conf >= 70:
        nivel = "ALTA"
    elif conf >= 60:
        nivel = "MODERADA"
    else:
        nivel = "BAJA"

    price = signal.get("price", 0)
    trade = signal.get("trade", {})
    grid = signal.get("grid", {})

    msg = (
        f"{emoji} *{signal['symbol']}*\n"
        f"\n"
        f"Tendencia *{texto}*\n"
        f"Confianza: *{nivel} ({conf:.0f}%)*\n"
        f"Precio actual: `${price:,.2f}`\n"
        f"Operación sugerida: *{accion}*\n"
    )

    # Trade info
    if trade:
        msg += (
            f"\n📊 *Trade*\n"
            f"Entrada: `${trade.get('entry', 0):,.2f}`\n"
            f"Target: `${trade.get('target', 0):,.2f}`\n"
            f"Stop: `${trade.get('stop', 0):,.2f}`\n"
            f"Mov. esperado: `{trade.get('move_pct', 0):+.2f}%`\n"
        )

    # Grid Bot config
    if grid:
        msg += (
            f"\n🤖 *Grid Bot Futuros {trade.get('leverage', 0)}x*\n"
            f"Rango: `${grid.get('lower', 0):,.0f}` — `${grid.get('upper', 0):,.0f}`\n"
            f"Grillas: *{grid.get('num_grids', 0)}*\n"
            f"Rango total: `{grid.get('range_pct', 0):.2f}%`\n"
            f"Espacio/grilla: `${grid.get('spacing_usd', 0):,.0f}` (`{grid.get('spacing_pct', 0):.3f}%`)\n"
            f"Ganancia/grilla: `${grid.get('profit_per_grid', 0):.2f}`\n"
            f"Fee/grilla: `${grid.get('fee_per_grid', 0):.2f}`\n"
            f"Neto/grilla: `${grid.get('net_per_grid', 0):.2f}`\n"
            f"⚠️ Liquidación: `${grid.get('liq_price', 0):,.0f}`\n"
        )

    # Contexto macro 1H
    ctx = signal.get("context", {})
    if ctx:
        _trend_label = {
            "STRONG_BULL": "Alcista fuerte (precio > EMA50/200)",
            "RECOVERING":  "Recuperando (precio > EMA50)",
            "WEAKENING":   "Debilitándose (precio < EMA50)",
            "STRONG_BEAR": "Bajista fuerte (precio < EMA50/200)",
            "NEUTRAL":     "Neutral",
        }
        trend_txt = _trend_label.get(ctx.get("trend_1h", "NEUTRAL"), "Neutral")

        stoch_k = ctx.get("stoch_k_1h", 50)
        stoch_d = ctx.get("stoch_d_1h", 50)
        stoch_flag = ""
        if ctx.get("stoch_overbought"):
            stoch_flag = " ⚠️ sobrecompra"
        elif ctx.get("stoch_oversold"):
            stoch_flag = " ⚠️ sobreventa"

        obv_map = {"UP": "alcista", "DOWN": "bajista", "NEUTRAL": "neutral"}
        obv_div_map = {"BULL": "divergencia alcista", "BEAR": "divergencia bajista", "NONE": "sin divergencia"}
        obv_txt = obv_map.get(ctx.get("obv_trend", "NEUTRAL"), "neutral")
        obv_div = obv_div_map.get(ctx.get("obv_divergence", "NONE"), "sin divergencia")

        msg += (
            f"\n📡 *Contexto 1H*\n"
            f"Tendencia: {trend_txt}\n"
            f"StochRSI: `K={stoch_k:.0f} D={stoch_d:.0f}`{stoch_flag}\n"
            f"OBV: `{obv_txt}` ({obv_div})\n"
        )

        if ctx.get("golden_cross"):
            msg += "🏆 `Golden Cross EMA50/200` ¡señal alcista macro!\n"
        elif ctx.get("death_cross"):
            msg += "💀 `Death Cross EMA50/200` ¡señal bajista macro!\n"

        sup = ctx.get("nearest_support", 0)
        res = ctx.get("nearest_resistance", 0)
        if sup and res:
            msg += (
                f"Soporte 1H:     `${sup:,.0f}` ({ctx.get('dist_to_support_pct', 0):.2f}% abajo)\n"
                f"Resistencia 1H: `${res:,.0f}` ({ctx.get('dist_to_resistance_pct', 0):.2f}% arriba)\n"
            )

        ema50 = ctx.get("ema50", 0)
        ema200 = ctx.get("ema200", 0)
        if ema50:
            msg += f"EMA50 1H: `${ema50:,.0f}`"
            if ema200:
                msg += f"  EMA200 1H: `${ema200:,.0f}`"
            msg += "\n"

    # Razones
    reasons = signal.get("reasons", [])
    if reasons:
        msg += f"\n📋 *Señales*\n"
        for r in reasons:
            msg += f"• {r}\n"

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    msg += f"\n🕐 _{ts}_"

    return msg


def send(message: str, max_retries: int = 3) -> bool:
    """Envía un mensaje a Telegram con reintentos. Retorna True si fue exitoso."""
    if not BOT_TOKEN or not CHAT_ID:
        log.error("TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados en .env")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }

    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                log.info("Mensaje enviado a Telegram.")
                return True
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 30))
                log.warning(f"Rate limit Telegram. Esperando {retry_after}s...")
                time.sleep(retry_after)
                continue
            log.error(f"Error Telegram {resp.status_code}: {resp.text}")
            return False
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                log.error(f"Fallo al enviar a Telegram tras {max_retries} intentos: {e}")
                return False
            wait = 2 ** attempt
            log.warning(f"Error de red Telegram (intento {attempt+1}): {e}. Reintentando en {wait}s...")
            time.sleep(wait)

    return False


def notify(signal: dict) -> bool:
    """Envía una predicción al dashboard web y por Telegram."""
    web.push_alert(signal)
    msg = format_message(signal)
    return send(msg)


def format_bmsb_message(signal: dict) -> str:
    """Formatea una alerta de Bull Market Support Band para Telegram."""
    direction = signal["direction"]
    symbol    = signal["symbol"]
    price     = signal["price"]
    sma20     = signal["sma20"]
    ema21     = signal["ema21"]
    dist_sma  = signal["dist_sma20_pct"]
    dist_ema  = signal["dist_ema21_pct"]
    prev_raw  = signal.get("prev_zone", "UNKNOWN")

    # Etiqueta legible para la zona anterior
    if prev_raw in ("UNKNOWN", "?", None, ""):
        prev_label = "Sin historial previo"
        is_first   = True
    else:
        prev_label = prev_raw
        is_first   = False

    if direction == "BULL":
        emoji     = "🟢"
        headline  = "Mercado ALCISTA confirmado"
        detail    = "El precio superó ambas bandas semanales.\nContexto macro: favorable para compras."
        dist_sma_txt = f"+{dist_sma:.1f}% sobre la banda"
        dist_ema_txt = f"+{dist_ema:.1f}% sobre la banda"
    else:
        emoji     = "🔴"
        headline  = "Mercado BAJISTA confirmado"
        detail    = "El precio cayó bajo ambas bandas semanales.\nContexto macro: precaución, evitar compras."
        dist_sma_txt = f"{dist_sma:.1f}% bajo la banda"
        dist_ema_txt = f"{dist_ema:.1f}% bajo la banda"

    zone_line = (
        f"_Primera detección desde que arrancó el bot_"
        if is_first else
        f"Cambio: `{prev_label}` → *{direction}*"
    )

    ts = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    msg = (
        f"{emoji} *{symbol}*\n"
        f"*Banda de Soporte Semanal (BMSB)*\n"
        f"\n"
        f"*{headline}*\n"
        f"{detail}\n"
        f"\n"
        f"💰 Precio:  `${price:,.2f}`\n"
        f"📈 SMA 20W: `${sma20:,.2f}`  _({dist_sma_txt})_\n"
        f"📉 EMA 21W: `${ema21:,.2f}`  _({dist_ema_txt})_\n"
        f"\n"
        f"🔄 {zone_line}\n"
        f"\n"
        f"⏱ _Semanal (1W) · {ts}_"
    )
    return msg


def notify_bmsb(signal: dict) -> bool:
    """Envía una alerta BMSB al dashboard web y por Telegram."""
    web.push_alert(signal)
    msg = format_bmsb_message(signal)
    return send(msg)
