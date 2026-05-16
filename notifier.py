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
    symbol = signal["symbol"]
    price = signal["price"]
    sma20 = signal["sma20"]
    ema21 = signal["ema21"]
    dist_sma = signal["dist_sma20_pct"]
    dist_ema = signal["dist_ema21_pct"]
    prev_zone = signal.get("prev_zone", "?")

    if direction == "BULL":
        emoji = "🟢"
        titulo = "CRUCE ALCISTA — Mercado Bull"
        desc = "El precio superó ambas bandas semanales ✅\nConfirmación de tendencia alcista macro."
        rel_sma = f"+{dist_sma:.2f}%" if dist_sma >= 0 else f"{dist_sma:.2f}%"
        rel_ema = f"+{dist_ema:.2f}%" if dist_ema >= 0 else f"{dist_ema:.2f}%"
    else:
        emoji = "🔴"
        titulo = "CRUCE BAJISTA — Alerta Macro"
        desc = "El precio cayó por debajo de ambas bandas semanales ⚠️\nSeñal de debilidad macro."
        rel_sma = f"{dist_sma:.2f}%"
        rel_ema = f"{dist_ema:.2f}%"

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    msg = (
        f"{emoji} *{symbol} — Bull Market Support Band*\n"
        f"\n"
        f"📊 *{titulo}*\n"
        f"{desc}\n"
        f"\n"
        f"💰 Precio actual: `${price:,.2f}`\n"
        f"📈 SMA 20W:       `${sma20:,.2f}` ({rel_sma})\n"
        f"📉 EMA 21W:       `${ema21:,.2f}` ({rel_ema})\n"
        f"\n"
        f"↩️ Zona anterior: `{prev_zone}`  →  Zona actual: `{direction}`\n"
        f"\n"
        f"⏱ Timeframe: *Semanal (1W)*\n"
        f"🕐 _{ts}_"
    )
    return msg


def notify_bmsb(signal: dict) -> bool:
    """Envía una alerta BMSB al dashboard web y por Telegram."""
    web.push_alert(signal)
    msg = format_bmsb_message(signal)
    return send(msg)
