# Trading alert — Predicción Pre-Breakout para Futuros

Bot de alertas técnicas para **BTC/USDT**, **ETH/USDT** y **SOL/USDT** que opera en dos capas:

| Capa                         | Timeframe     | Propósito                                              |
| ---------------------------- | ------------- | ------------------------------------------------------ |
| **Pre-breakout (futuros)**   | 1m / 5m / 15m | Detectar movimientos inminentes para operar LONG/SHORT |
| **Bull Market Support Band** | Semanal (1W)  | Contexto macro: ¿estamos en bull o bear market?        |

Las alertas se envían por **Telegram** con precio, niveles de entrada/target/stop y configuración de Grid Bot.

---

## Indicadores técnicos

### Capa intradía (futuros)

| Indicador                    | Qué detecta                                               | Timeframes  |
| ---------------------------- | --------------------------------------------------------- | ----------- |
| **Bollinger Squeeze**        | Volatilidad comprimida → breakout inminente               | 1m, 5m, 15m |
| **Divergencia RSI**          | Discrepancia precio/momentum → reversión                  | 1m, 5m      |
| **Pico de volumen**          | Volumen anómalo sin movimiento → acumulación/distribución | 1m          |
| **MACD pre-cruce**           | Histograma convergiendo a 0 → cruce inminente             | 1m, 5m      |
| **EMA 9/21 multi-TF**        | Confirmación de tendencia alineada                        | 1m, 5m, 15m |
| **Cascada de momentum**      | 3+ velas consecutivas acelerando                          | 1m, 5m      |
| **Expansión de volatilidad** | ATR reciente > ATR histórico × 1.5                        | 1m, 5m      |

Las señales se combinan con **puntuación ponderada**. Solo alerta si:

- Confianza ≥ 60 %
- Movimiento esperado ≥ 0.3 %
- Cooldown de 5 minutos por par + dirección

### Bull Market Support Band (1W)

Compara el precio con dos medias en timeframe semanal:

```
SMA 20 semanas  +  EMA 21 semanas
```

| Zona        | Condición                         | Alerta                         |
| ----------- | --------------------------------- | ------------------------------ |
| **BULL**    | Precio por encima de ambas bandas | Solo al cruzar desde abajo ✅  |
| **BEAR**    | Precio por debajo de ambas bandas | Solo al cruzar desde arriba ⚠️ |
| **NEUTRAL** | Precio entre las dos bandas       | Sin alerta                     |

- Usa la última vela semanal **cerrada** para evitar señales falsas de la vela en curso.
- Cooldown de **7 días** por par + dirección.
- Se chequea cada **60 segundos** dentro del loop principal.

---

## Instalación

**Requisitos:** Python 3.11+

```bash
# Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

# Instalar dependencias
pip install -r requirements.txt
```

---

## Configuración

Crear el archivo `.env` en la raíz del proyecto:

```env
TELEGRAM_BOT_TOKEN=123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=987654321
```

### Cómo obtener el token y el chat ID

1. Abrí Telegram → buscá **@BotFather** → `/newbot` → copiá el token.
2. Buscá **@userinfobot** → `/start` → copiá tu `id` como `TELEGRAM_CHAT_ID`.

### Parámetros configurables (signals.py)

| Variable             | Por defecto | Descripción                               |
| -------------------- | ----------- | ----------------------------------------- |
| `TRADE_AMOUNT`       | `2000` USDT | Capital por operación                     |
| `LEVERAGE`           | `15x`       | Apalancamiento                            |
| `COOLDOWN_SECONDS`   | `300`       | Tiempo mínimo entre alertas del mismo par |
| `MIN_MOVE_PCT`       | `0.3 %`     | Movimiento mínimo esperado para alertar   |
| `MIN_CONFIDENCE`     | `60 %`      | Confianza mínima para alertar             |
| `BMSB_COOLDOWN_DAYS` | `7`         | Días de cooldown entre alertas BMSB       |

---

## Uso

### Un análisis único (prueba)

```bash
python main.py
```

Ejecuta un solo tick de análisis y sale. Útil para verificar que todo funciona.

### Modo live (producción)

```bash
python main.py --live
```

Loop continuo. Analiza cada segundo, chequea BMSB cada 60 segundos.
Al arrancar **abre automáticamente el dashboard en el browser** (`http://localhost:5000`).
Presioná `Ctrl+C` para detener.

### Dashboard web

Disponible en `http://localhost:5000` mientras corra `--live`.

- **Tickers en tiempo real**: precio en vivo de cada par con color verde/rojo según el movimiento
- **Alertas de futuros**: dirección, confianza, precio, entrada/target/stop, PnL estimado, configuración del grid bot, señales técnicas que dispararon la alerta
- **Alertas BMSB**: zona anterior → actual, valores de SMA 20W y EMA 21W con distancia porcentual al precio
- Las alertas nuevas aparecen **arriba** con animación; las antiguas se conservan durante la sesión

### Herramientas de diagnóstico

```bash
# Ver todos los indicadores en tiempo real (sin Telegram)
python debug.py

# Simular escenarios con datos sintéticos
python test_signals.py

# Probar envío a Telegram
python test_telegram.py
```

---

## Estructura de archivos

```
trading-day/
├── main.py          # Scheduler, loop principal, punto de entrada
├── data.py          # Obtención de datos OHLCV via Binance (ccxt) con caché
├── indicators.py    # Cálculo de todos los indicadores técnicos + BMSB
├── signals.py       # Lógica de scoring, filtros y decisión de alertas
├── notifier.py      # Formateo y envío de mensajes a Telegram + web push
├── web.py           # Dashboard web local (Flask + SSE, HTML inline)
├── state.json       # Estado persistido (cooldowns, zona BMSB por par)
├── trading-bot.log  # Log de ejecución (se crea al correr)
├── .env             # Credenciales (no commitear)
├── requirements.txt
├── debug.py         # Diagnóstico de indicadores en tiempo real
├── test_signals.py  # Tests de escenarios con datos sintéticos
└── test_telegram.py # Test de conectividad con Telegram
```

---

## Ejemplo de alertas Telegram

### Alerta de futuros (pre-breakout)

```
🟢 BTC/USDT

Tendencia ALCISTA
Confianza: ALTA (74%)
Precio actual: $103,450.00
Operación sugerida: LONG

📊 Trade
Entrada: $103,450.00
Target: $104,230.00
Stop:   $103,138.00
Mov. esperado: +0.75%

🤖 Grid Bot Futuros 15x
Rango: $102,900 — $104,800
Grillas: 12  |  Rango: 1.84%
Neto/grilla: $36.80

📋 Señales
• BB squeeze 1m (precio arriba)
• Divergencia alcista RSI 5m (38)
• MACD cruce alcista inminente 5m
• EMA alineadas BULL (1m+5m+15m)

🕐 2026-05-16 12:50 UTC
```

### Alerta BMSB semanal

```
🟢 BTC/USDT — Bull Market Support Band

📊 CRUCE ALCISTA — Mercado Bull
El precio superó ambas bandas semanales ✅
Confirmación de tendencia alcista macro.

💰 Precio actual: $98,500.00
📈 SMA 20W:       $94,200.00 (+4.57%)
📉 EMA 21W:       $95,100.00 (+3.57%)

↩️ Zona anterior: BEAR  →  Zona actual: BULL

⏱ Timeframe: Semanal (1W)
🕐 2026-05-16 00:10 UTC
```

---

## Despliegue en producción (VPS)

```bash
# Instalar como servicio systemd (Linux)
sudo nano /etc/systemd/system/trading-bot.service
```

```ini
[Unit]
Description=Trading Day Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/trading-day
ExecStart=/home/ubuntu/trading-day/.venv/bin/python main.py --live
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable trading-bot
sudo systemctl start trading-bot
sudo journalctl -u trading-bot -f   # ver logs en tiempo real
```

---

## Notas importantes

- Este bot es una **herramienta de análisis técnico**, no un consejo financiero.
- Siempre verificá la señal antes de operar. El bot puede generar falsas señales en mercados laterales o de muy baja volatilidad.
- El BMSB semanal es una señal macro. Un cruce bajista no significa caída inmediata; puede tardar semanas en desarrollarse.
- Operando futuros con 15x de apalancamiento, el riesgo de liquidación es real. Gestioná el tamaño de posición según tu tolerancia al riesgo.
