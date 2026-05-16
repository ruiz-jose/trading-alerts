import os

import requests
from dotenv import load_dotenv

load_dotenv()


def send_telegram_message(message: str) -> None:
    """Envía un mensaje a Telegram usando el bot configurado en .env."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("Error: TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no están configurados en .env")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("Mensaje enviado correctamente a Telegram.")
        else:
            print(f"Error al enviar mensaje: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Excepción al enviar mensaje: {e}")


if __name__ == "__main__":
    test_message = "Este es un mensaje de prueba desde el script de test."
    send_telegram_message(test_message)