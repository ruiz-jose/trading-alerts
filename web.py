"""Servidor web — dashboard de alertas en tiempo real.

Levanta Flask en un hilo daemon y expone:
    GET /        → dashboard HTML
    GET /stream  → Server-Sent Events (alertas + precios en vivo)
    GET /health  → health-check para Railway/Render

Uso desde main.py:
    web.start()          # arranca el servidor (una sola vez)
    web.push_alert(sig)  # envía una alerta a todos los clientes conectados
    web.push_scan(data)  # envía un precio de escaneo
"""

import json
import logging
import os
import queue
import threading
import time
import webbrowser

from flask import Flask, Response, jsonify

log = logging.getLogger(__name__)

# ── Pub/sub: lista de colas por cliente SSE ───────────────────────────────────
_clients: list[queue.Queue] = []
_clients_lock = threading.Lock()

# ── Estado de diagnóstico ─────────────────────────────────────────────────────
_status: dict = {
    "last_scan_ts": None,
    "last_error": None,
    "last_error_ts": None,
    "ticks_ok": 0,
    "ticks_failed": 0,
}

app = Flask(__name__)
app.logger.disabled = True  # silenciar el logger de Flask


def _broadcast(event_type: str, data: dict) -> None:
    """Envía un evento a todos los clientes SSE conectados."""
    with _clients_lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait({"event": event_type, "data": data})
            except queue.Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)


def push_alert(signal: dict) -> None:
    """Empuja una alerta (futuros o BMSB) al dashboard."""
    _broadcast("alert", signal)


def push_scan(scan_data: dict) -> None:
    """Empuja un tick de escaneo (precio en vivo) al dashboard."""
    _status["last_scan_ts"] = time.time()
    _status["ticks_ok"] += 1
    _broadcast("scan", scan_data)


def push_error(message: str) -> None:
    """Empuja un error al dashboard y lo registra en el estado."""
    _status["last_error"] = message
    _status["last_error_ts"] = time.time()
    _status["ticks_failed"] += 1
    _broadcast("bot_error", {"message": message})


# ── Rutas Flask ───────────────────────────────────────────────────────────────

@app.route("/")
def index() -> str:
    return _HTML


@app.route("/health")
def health() -> Response:
    return Response("ok", status=200, content_type="text/plain")


@app.route("/api/status")
def api_status() -> Response:
    now = time.time()
    last_scan_ago = (now - _status["last_scan_ts"]) if _status["last_scan_ts"] else None
    last_err_ago  = (now - _status["last_error_ts"]) if _status["last_error_ts"] else None
    return jsonify({
        "ok": _status["last_scan_ts"] is not None and last_scan_ago < 30,
        "last_scan_seconds_ago": round(last_scan_ago, 1) if last_scan_ago is not None else None,
        "last_error": _status["last_error"],
        "last_error_seconds_ago": round(last_err_ago, 1) if last_err_ago is not None else None,
        "ticks_ok": _status["ticks_ok"],
        "ticks_failed": _status["ticks_failed"],
    })


@app.route("/stream")
def stream() -> Response:
    """Endpoint SSE: mantiene conexión abierta y envía eventos al cliente."""
    q: queue.Queue = queue.Queue(maxsize=200)
    with _clients_lock:
        _clients.append(q)

    def generate():
        try:
            while True:
                try:
                    item = q.get(timeout=20)
                    yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"  # keep-alive para evitar timeout del browser
        finally:
            with _clients_lock:
                if q in _clients:
                    _clients.remove(q)

    return Response(
        generate(),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Arranque ──────────────────────────────────────────────────────────────────

def start(port: int | None = None, open_browser: bool = True) -> None:
    """Inicia Flask en un hilo daemon. Llama solo una vez."""
    import logging as _logging
    _logging.getLogger("werkzeug").setLevel(_logging.ERROR)

    # En cloud (Railway/Render) se usa la variable PORT del entorno
    _port = port or int(os.environ.get("PORT", 5000))
    _host = "0.0.0.0"

    def _run():
        app.run(host=_host, port=_port, debug=False,
                use_reloader=False, threaded=True)

    t = threading.Thread(target=_run, daemon=True, name="flask-web")
    t.start()
    log.info(f"Dashboard disponible en http://localhost:{_port}")

    if open_browser:
        def _open():
            import time
            time.sleep(1.5)  # esperar a que Flask arranque
            webbrowser.open(f"http://127.0.0.1:{_port}")
        threading.Thread(target=_open, daemon=True, name="browser-open").start()


# ── HTML inline ───────────────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trading alerts</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh}

/* HEADER */
header{background:#161b22;border-bottom:1px solid #21262d;padding:13px 20px;display:flex;align-items:center;gap:11px;position:sticky;top:0;z-index:50}
header h1{font-size:15px;font-weight:600;color:#58a6ff;letter-spacing:.02em}
.dot{width:9px;height:9px;border-radius:50%;flex-shrink:0;background:#d29922}
.dot.on{background:#3fb950;animation:blink 2s ease infinite}
.dot.off{background:#f85149;animation:none}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
.hstatus{font-size:12px;color:#8b949e}
.hcount{margin-left:auto;font-size:12px;color:#6e7681;background:#21262d;padding:3px 11px;border-radius:20px;white-space:nowrap}

/* TICKERS */
.tickers{display:flex;gap:10px;padding:10px 20px;background:#0d1117;border-bottom:1px solid #21262d;overflow-x:auto;min-height:72px;align-items:center}
.ticker{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:8px 14px;min-width:130px;flex-shrink:0;transition:border-color .3s}
.ticker.flash-up{border-color:#3fb950}
.ticker.flash-dn{border-color:#f85149}
.tk-sym{font-size:10px;font-weight:700;color:#8b949e;letter-spacing:.08em}
.tk-price{font-size:17px;font-weight:700;font-family:monospace;color:#e6edf3;transition:color .4s}
.tk-ts{font-size:10px;color:#6e7681;margin-top:2px}
.up{color:#3fb950!important}.dn{color:#f85149!important}

/* MAIN */
main{max-width:860px;margin:0 auto;padding:18px 14px}

/* EMPTY */
.empty{text-align:center;padding:64px 20px;color:#6e7681}
.empty svg{opacity:.25;margin-bottom:14px}
.empty h2{font-size:15px;font-weight:500;color:#8b949e;margin-bottom:5px}
.empty p{font-size:13px}
@keyframes spin{to{transform:rotate(360deg)}}
.spinner{animation:spin 3s linear infinite;display:block;margin:0 auto}

/* SECTION */
.sec{font-size:11px;font-weight:600;color:#6e7681;text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;margin-top:20px}

/* CARDS */
.feed{display:flex;flex-direction:column;gap:12px}
.card{background:#161b22;border:1px solid #21262d;border-radius:10px;overflow:hidden;animation:drop .25s ease}
@keyframes drop{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}
.card.long{border-left:4px solid #3fb950}
.card.short{border-left:4px solid #f85149}
.card.bull{border-left:4px solid #58a6ff}
.card.bear{border-left:4px solid #d29922}

.card-head{display:flex;align-items:center;justify-content:space-between;padding:12px 14px 10px}
.card-title{display:flex;align-items:center;gap:7px}
.card-sym{font-size:15px;font-weight:700}
.card-time{font-size:11px;color:#6e7681;white-space:nowrap}
.card-body{padding:0 14px 13px}

/* BADGES */
.badge{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.05em;padding:2px 8px;border-radius:20px}
.badge.long{background:rgba(63,185,80,.15);color:#3fb950}
.badge.short{background:rgba(248,81,73,.15);color:#f85149}
.badge.bull{background:rgba(88,166,255,.15);color:#58a6ff}
.badge.bear{background:rgba(210,153,34,.15);color:#d29922}
.badge.bmsb{background:rgba(139,148,158,.1);color:#8b949e;font-size:9px;letter-spacing:.07em}

/* PILLS */
.pills{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.pill{background:#21262d;border-radius:5px;padding:4px 9px;font-size:11px;font-family:monospace;white-space:nowrap}
.pill b{color:#8b949e;font-weight:500;margin-right:3px}

/* LEVELS */
.levels{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:10px}
.lvl{background:#21262d;border-radius:6px;padding:7px 9px;text-align:center}
.lvl-lbl{font-size:9px;color:#6e7681;text-transform:uppercase;letter-spacing:.07em;margin-bottom:3px}
.lvl-val{font-size:13px;font-weight:600;font-family:monospace}
.lvl-val.e{color:#e6edf3}.lvl-val.t{color:#3fb950}.lvl-val.s{color:#f85149}

/* GRID BOT */
.grid-box{background:#21262d;border-radius:6px;padding:9px 12px;margin-bottom:10px;font-size:12px}
.grid-row{display:flex;justify-content:space-between;padding:2px 0;color:#8b949e}
.grid-row span:last-child{color:#e6edf3;font-family:monospace}
.liq-row{color:#f85149!important}
.liq-row span:last-child{color:#f85149!important}

/* REASONS */
.reasons{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.reason{font-size:11px;background:#21262d;border:1px solid #30363d;border-radius:4px;padding:2px 7px;color:#8b949e}

/* BANDS */
.bands{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.band{background:#21262d;border-radius:6px;padding:8px 12px}
.band-lbl{font-size:10px;color:#6e7681;margin-bottom:3px;text-transform:uppercase;letter-spacing:.06em}
.band-val{font-size:14px;font-weight:700;font-family:monospace}
.band-dist{font-size:11px;color:#8b949e;margin-top:2px}

/* ZONE ARROW */
.zone-row{display:flex;align-items:center;gap:8px;margin-bottom:10px;font-size:12px;color:#8b949e}
.zone-pill{background:#21262d;border-radius:4px;padding:3px 9px;font-weight:600;font-size:11px;font-family:monospace}

/* CONTEXT 1H */
.ctx-box{background:#21262d;border-radius:6px;padding:9px 12px;margin-bottom:10px;font-size:12px}
.ctx-row{display:flex;justify-content:space-between;align-items:center;padding:2px 0;color:#8b949e}
.ctx-row span:last-child{color:#e6edf3;font-family:monospace;text-align:right;max-width:60%}
.ctx-trend-STRONG_BULL{color:#3fb950!important}
.ctx-trend-RECOVERING{color:#56d364!important}
.ctx-trend-WEAKENING{color:#d29922!important}
.ctx-trend-STRONG_BEAR{color:#f85149!important}
.ctx-trend-NEUTRAL{color:#8b949e!important}
.ctx-cross-golden{color:#f0c000;font-weight:700}
.ctx-cross-death{color:#f85149;font-weight:700}
.sr-bar{display:flex;align-items:center;gap:4px;margin:6px 0;font-size:11px;color:#6e7681}
.sr-line{flex:1;height:3px;background:#30363d;border-radius:2px;position:relative;overflow:visible}
.sr-price-dot{position:absolute;width:8px;height:8px;background:#58a6ff;border-radius:50%;top:-2.5px;transform:translateX(-50%)}

/* SCROLLBAR */
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:#0d1117}
::-webkit-scrollbar-thumb{background:#30363d;border-radius:3px}
</style>
</head>
<body>

<header>
  <div class="dot" id="dot"></div>
  <h1>Trading alerts</h1>
  <span class="hstatus" id="hstatus">Conectando...</span>
  <span class="hcount" id="hcount">0 alertas</span>
</header>

<div class="tickers" id="tickers"></div>

<main>
  <div class="empty" id="empty">
    <svg class="spinner" id="spinner" width="44" height="44" viewBox="0 0 24 24" fill="none"
         stroke="#58a6ff" stroke-width="1.5" stroke-linecap="round">
      <path d="M12 2a10 10 0 1 0 10 10" />
    </svg>
    <svg id="error-icon" width="44" height="44" viewBox="0 0 24 24" fill="none"
         stroke="#f85149" stroke-width="1.5" stroke-linecap="round" style="display:none;margin:0 auto 14px">
      <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><circle cx="12" cy="16" r=".5" fill="#f85149"/>
    </svg>
    <h2 id="empty-title">Escaneando el mercado...</h2>
    <p id="empty-msg">Las alertas aparecerán aquí cuando se detecte una señal</p>
    <p id="error-detail" style="margin-top:8px;font-size:11px;color:#f85149;font-family:monospace;max-width:480px;word-break:break-all;display:none"></p>
  </div>

  <div id="feed-wrap" style="display:none">
    <div class="sec">Alertas recientes</div>
    <div class="feed" id="feed"></div>
  </div>
</main>

<script>
const prevPrices = {};
let alertCount = 0;

const es = new EventSource('/stream');

es.onopen = () => {
  document.getElementById('dot').className = 'dot on';
  document.getElementById('hstatus').textContent = 'En vivo';
};
es.onerror = () => {
  document.getElementById('dot').className = 'dot off';
  document.getElementById('hstatus').textContent = 'Reconectando...';
};

es.addEventListener('scan',  e => updateTicker(JSON.parse(e.data)));
es.addEventListener('alert', e => addAlert(JSON.parse(e.data)));
es.addEventListener('bot_error', e => showError(JSON.parse(e.data).message));

function showError(msg) {
  const empty = document.getElementById('empty');
  if (empty.style.display === 'none') return; // hay alertas, no mostrar
  document.getElementById('spinner').style.display    = 'none';
  document.getElementById('error-icon').style.display = 'block';
  document.getElementById('empty-title').textContent  = 'Error al obtener datos';
  document.getElementById('empty-msg').textContent    = 'El bot no puede conectar con el exchange. Revisa los logs de Render.';
  const det = document.getElementById('error-detail');
  det.style.display   = 'block';
  det.textContent     = msg;
}

/* ── Tickers ─────────────────────────────────────────────── */
function updateTicker({ symbol, price, ts }) {
  const sid = 'tk-' + symbol.replace('/', '-');
  let el = document.getElementById(sid);
  if (!el) {
    el = document.createElement('div');
    el.className = 'ticker';
    el.id = sid;
    el.innerHTML =
      '<div class="tk-sym">' + symbol + '</div>' +
      '<div class="tk-price" id="p-' + sid + '">—</div>' +
      '<div class="tk-ts"   id="t-' + sid + '">—</div>';
    document.getElementById('tickers').appendChild(el);
  }
  const prev = prevPrices[symbol];
  const pEl  = document.getElementById('p-' + sid);
  pEl.textContent = '$' + price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  pEl.className = 'tk-price' + (prev == null ? '' : price > prev ? ' up' : price < prev ? ' dn' : '');
  el.classList.remove('flash-up', 'flash-dn');
  if (prev != null) {
    void el.offsetWidth; // reflow para reiniciar animación
    el.classList.add(price > prev ? 'flash-up' : price < prev ? 'flash-dn' : '');
  }
  document.getElementById('t-' + sid).textContent = ts;
  prevPrices[symbol] = price;
}

/* ── Formato de números ──────────────────────────────────── */
function fmt(n, dec = 2) {
  return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
function pct(n) {
  return (n >= 0 ? '+' : '') + Number(n).toFixed(2) + '%';
}
function nowStr() {
  return new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/* ── Alertas ─────────────────────────────────────────────── */
function addAlert(sig) {
  document.getElementById('empty').style.display = 'none';
  document.getElementById('feed-wrap').style.display = 'block';
  alertCount++;
  document.getElementById('hcount').textContent =
    alertCount + (alertCount === 1 ? ' alerta' : ' alertas');

  const dir  = sig.direction.toLowerCase();
  const card = document.createElement('div');
  card.className = 'card ' + dir;

  if (sig.type === 'BMSB') {
    card.innerHTML = buildBMSB(sig, dir);
  } else {
    card.innerHTML = buildFutures(sig, dir);
  }

  const feed = document.getElementById('feed');
  feed.insertBefore(card, feed.firstChild);
}

function buildBMSB(sig, dir) {
  const prev = sig.prev_zone;
  const isFirst = !prev || prev === 'UNKNOWN' || prev === '?';

  // Línea de transición de zona
  let zoneHtml;
  if (isFirst) {
    zoneHtml =
      '<div class="zone-row" style="font-style:italic;color:#6e7681">' +
        'Primera detección desde que arrancó el bot' +
      '</div>';
  } else {
    zoneHtml =
      '<div class="zone-row">' +
        '<span style="color:#6e7681">Cambio de zona</span>' +
        '<span class="zone-pill">' + prev + '</span>' +
        '<span style="color:#6e7681">→</span>' +
        '<span class="zone-pill" style="font-weight:700">' + sig.direction + '</span>' +
      '</div>';
  }

  // Texto descriptivo según dirección
  const descTxt = dir === 'bull'
    ? 'El precio superó ambas bandas semanales. Mercado macro alcista.'
    : 'El precio cayó bajo ambas bandas semanales. Precaución: mercado macro bajista.';

  // Distancia al precio con signo y color
  function bandDist(pctVal) {
    const n = Number(pctVal);
    const sign = n >= 0 ? '+' : '';
    const col  = n >= 0 ? '#3fb950' : '#f85149';
    return '<span style="color:' + col + ';font-size:11px">' + sign + n.toFixed(1) + '% vs precio</span>';
  }

  return (
    '<div class="card-head">' +
      '<div class="card-title">' +
        '<span class="badge bmsb">1W · BMSB</span>' +
        '<span class="badge ' + dir + '">' + sig.direction + '</span>' +
        '<span class="card-sym">' + sig.symbol + '</span>' +
      '</div>' +
      '<span class="card-time">' + nowStr() + '</span>' +
    '</div>' +
    '<div class="card-body">' +
      '<p style="font-size:12px;color:#8b949e;margin-bottom:10px">' + descTxt + '</p>' +
      zoneHtml +
      '<div class="pills" style="margin-bottom:10px">' +
        '<div class="pill"><b>Precio actual</b>' + fmt(sig.price) + '</div>' +
      '</div>' +
      '<div class="bands">' +
        '<div class="band">' +
          '<div class="band-lbl">SMA 20 semanas</div>' +
          '<div class="band-val">' + fmt(sig.sma20) + '</div>' +
          '<div class="band-dist">' + bandDist(sig.dist_sma20_pct) + '</div>' +
        '</div>' +
        '<div class="band">' +
          '<div class="band-lbl">EMA 21 semanas</div>' +
          '<div class="band-val">' + fmt(sig.ema21) + '</div>' +
          '<div class="band-dist">' + bandDist(sig.dist_ema21_pct) + '</div>' +
        '</div>' +
      '</div>' +
    '</div>'
  );
}

function buildContext(ctx) {
  if (!ctx) return '';
  const trendLabel = {
    'STRONG_BULL': 'Alcista fuerte',
    'RECOVERING':  'Recuperando',
    'WEAKENING':   'Debilitándose',
    'STRONG_BEAR': 'Bajista fuerte',
    'NEUTRAL':     'Neutral',
  };
  const trend = ctx.trend_1h || 'NEUTRAL';
  const trendTxt = trendLabel[trend] || trend;

  const stochFlag = ctx.stoch_overbought ? ' ⚠ sobrecompra'
                  : ctx.stoch_oversold   ? ' ⚠ sobreventa'
                  : '';
  const obvMap = { UP: 'alcista', DOWN: 'bajista', NEUTRAL: 'neutral' };
  const divMap = { BULL: 'divergencia alcista', BEAR: 'divergencia bajista', NONE: '' };
  const obvTxt = (obvMap[ctx.obv_trend] || 'neutral') +
                 (divMap[ctx.obv_divergence] ? ' · ' + divMap[ctx.obv_divergence] : '');

  let crossHtml = '';
  if (ctx.golden_cross) crossHtml = '<div class="ctx-row"><span>Cruce</span><span class="ctx-cross-golden">🏆 Golden Cross EMA50/200</span></div>';
  else if (ctx.death_cross) crossHtml = '<div class="ctx-row"><span>Cruce</span><span class="ctx-cross-death">💀 Death Cross EMA50/200</span></div>';

  let srHtml = '';
  if (ctx.nearest_support && ctx.nearest_resistance) {
    srHtml =
      '<div class="ctx-row"><span>Soporte 1H</span><span>' +
        fmt(ctx.nearest_support, 0) + ' (' + Number(ctx.dist_to_support_pct).toFixed(2) + '% abajo)</span></div>' +
      '<div class="ctx-row"><span>Resistencia 1H</span><span>' +
        fmt(ctx.nearest_resistance, 0) + ' (' + Number(ctx.dist_to_resistance_pct).toFixed(2) + '% arriba)</span></div>';
  }

  let emaHtml = '';
  if (ctx.ema50) {
    emaHtml = '<div class="ctx-row"><span>EMA50/200 1H</span><span>' +
      fmt(ctx.ema50, 0) + (ctx.ema200 ? ' / ' + fmt(ctx.ema200, 0) : '') + '</span></div>';
  }

  return (
    '<div class="ctx-box">' +
      '<div class="ctx-row"><span>Tendencia 1H</span>' +
        '<span class="ctx-trend-' + trend + '">' + trendTxt + '</span></div>' +
      '<div class="ctx-row"><span>StochRSI 1H</span>' +
        '<span>K=' + Number(ctx.stoch_k_1h||50).toFixed(0) +
              ' D=' + Number(ctx.stoch_d_1h||50).toFixed(0) + stochFlag + '</span></div>' +
      '<div class="ctx-row"><span>OBV 5m</span><span>' + obvTxt + '</span></div>' +
      crossHtml +
      emaHtml +
      srHtml +
    '</div>'
  );
}

function buildFutures(sig, dir) {
  const t = sig.trade || {};
  const g = sig.grid  || {};
  const ctx = sig.context || null;
  const pnl = (t.expected_pnl || 0).toLocaleString('en-US', { maximumFractionDigits: 0 });

  let gridHtml = '';
  if (g.num_grids) {
    gridHtml =
      '<div class="grid-box">' +
        '<div class="grid-row"><span>Grid Bot ' + (t.leverage || '?') + 'x</span>' +
          '<span>' + fmt(g.lower, 0) + ' — ' + fmt(g.upper, 0) + '</span></div>' +
        '<div class="grid-row"><span>Grillas</span><span>' + g.num_grids + '  ·  rango ' + Number(g.range_pct).toFixed(2) + '%</span></div>' +
        '<div class="grid-row"><span>Neto / grilla</span><span>$' + Number(g.net_per_grid).toFixed(2) + '</span></div>' +
        '<div class="grid-row liq-row"><span>⚠ Liquidación</span><span>' + fmt(g.liq_price, 0) + '</span></div>' +
      '</div>';
  }

  const reasons = (sig.reasons || [])
    .map(r => '<span class="reason">' + r + '</span>')
    .join('');

  return (
    '<div class="card-head">' +
      '<div class="card-title">' +
        '<span class="badge ' + dir + '">' + sig.direction + '</span>' +
        '<span class="card-sym">' + sig.symbol + '</span>' +
      '</div>' +
      '<span class="card-time">' + nowStr() + '</span>' +
    '</div>' +
    '<div class="card-body">' +
      '<div class="pills">' +
        '<div class="pill"><b>Precio</b>'     + fmt(sig.price)                              + '</div>' +
        '<div class="pill"><b>Confianza</b>'  + Number(sig.confidence).toFixed(0) + '%'     + '</div>' +
        '<div class="pill"><b>Mov.</b>'       + pct(sig.move_pct)                           + '</div>' +
        '<div class="pill"><b>PnL est.</b>$'  + pnl                                         + '</div>' +
      '</div>' +
      '<div class="levels">' +
        '<div class="lvl"><div class="lvl-lbl">Entrada</div><div class="lvl-val e">' + fmt(t.entry)  + '</div></div>' +
        '<div class="lvl"><div class="lvl-lbl">Target</div><div class="lvl-val t">'  + fmt(t.target) + '</div></div>' +
        '<div class="lvl"><div class="lvl-lbl">Stop</div><div class="lvl-val s">'    + fmt(t.stop)   + '</div></div>' +
      '</div>' +
      buildContext(ctx) +
      gridHtml +
      '<div class="reasons">' + reasons + '</div>' +
    '</div>'
  );
}
</script>
</body>
</html>"""
