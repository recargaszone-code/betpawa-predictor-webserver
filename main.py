import os
import time
import threading
import re
import random
import traceback
import requests
from pathlib import Path
from flask import Flask, jsonify

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    StaleElementReferenceException,
    WebDriverException,
)

# ---------------- CONFIG
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PHONE = os.getenv("PHONE", "")
PASSWORD = os.getenv("PASSWORD", "")
URL = os.getenv("URL", "https://ebet.co.mz/games/go/spribe?id=aviator")

HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")
PORT = int(os.getenv("PORT", os.getenv("SERVER_PORT", "8080")))

SCREENSHOT_DIR = os.getenv("SCREENSHOT_DIR", "/tmp")
Path(SCREENSHOT_DIR).mkdir(parents=True, exist_ok=True)

BASE_BACKOFF = 8
MAX_BACKOFF = 600

app = Flask(__name__)

historico = []
_last_telegram = 0


# ---------------- TELEGRAM

def send_telegram(msg):
    global _last_telegram

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    now = time.time()

    if now - _last_telegram < 6:
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": msg,
                "parse_mode": "Markdown"
            },
            timeout=15
        )

        _last_telegram = now

    except Exception as e:
        print("Telegram error:", e)


# ---------------- SCREENSHOT

def screenshot(driver):

    path = os.path.join(
        SCREENSHOT_DIR,
        f"shot_{int(time.time())}.png"
    )

    try:
        driver.save_screenshot(path)
    except:
        pass


# ---------------- HISTORICO

def coletar_historico(driver):

    valores = []

    elementos = driver.find_elements(
        By.CSS_SELECTOR,
        "div.payouts-block div.payout"
    )

    for el in elementos:

        try:

            txt = el.text.strip()

            m = re.search(r"(\d+(\.\d+)?)", txt)

            if m:
                valores.append(float(m.group(1)))

        except:
            continue

    return valores


# ---------------- CHROME BIN

def detect_chrome():

    paths = [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome"
    ]

    for p in paths:
        if os.path.exists(p):
            return p

    return None


# ---------------- SCRAPER

def iniciar_scraper():

    global historico

    backoff = BASE_BACKOFF

    while True:

        driver = None

        try:

            print("Iniciando navegador")

            chrome_options = Options()

            if HEADLESS:
                chrome_options.add_argument("--headless=new")

            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1366,768")

            chrome_bin = detect_chrome()

            if chrome_bin:
                chrome_options.binary_location = chrome_bin

            service = None

            if os.path.exists("/usr/bin/chromedriver"):
                service = Service("/usr/bin/chromedriver")

            if service:
                driver = webdriver.Chrome(service=service, options=chrome_options)
            else:
                driver = webdriver.Chrome(options=chrome_options)

            driver.get(URL)

            time.sleep(8)

            print("Site aberto")

            send_telegram("🟢 Aviator iniciado")

            while True:

                try:

                    novos = coletar_historico(driver)

                    if novos and novos != historico:

                        historico = novos

                        ultimo = historico[0]

                        lista = ", ".join(
                            f"{v:.2f}x"
                            for v in historico[:20]
                        )

                        msg = f"""📊 AVIATOR

[{lista}]

Último: *{ultimo:.2f}x*
"""

                        print(msg)

                        send_telegram(msg)

                        screenshot(driver)

                    time.sleep(5)

                except StaleElementReferenceException:

                    time.sleep(1)

                except WebDriverException as e:

                    print("Webdriver error:", e)

                    break

        except Exception as e:

            print("Erro geral:", e)

            traceback.print_exc()

            send_telegram(f"🔥 ERRO: {e}")

            time.sleep(backoff)

            backoff = min(MAX_BACKOFF, backoff * 2)

        finally:

            try:

                if driver:
                    driver.quit()
            except:
                pass

            time.sleep(3)


# ---------------- API

@app.route("/api/history")
def api_history():
    return jsonify(historico)


@app.route("/api/last")
def api_last():

    if historico:
        return jsonify(historico[0])

    return jsonify(None)


@app.route("/")
def home():
    return "AVIATOR BOT ONLINE"


# ---------------- START

if __name__ == "__main__":

    t = threading.Thread(
        target=iniciar_scraper,
        daemon=True
    )

    t.start()

    app.run(
        host="0.0.0.0",
        port=PORT
    )
