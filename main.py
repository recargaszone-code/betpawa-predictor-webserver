import os
import time
import threading
import re
from flask import Flask, jsonify

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

app = Flask(__name__)

# ================= CONFIG =================
PHONE = os.getenv("BP_PHONE", "857789345")
PIN = os.getenv("BP_PIN", "2010")

URL = "https://www.betpawa.co.mz/games?gameId=aviator&filter=all&redirectBack=/games"

historico = []

# ================= DRIVER =================
def start_driver():

    chrome_options = Options()

    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1366,768")

    chrome_options.binary_location = "/usr/bin/chromium"

    service = Service("/usr/bin/chromedriver")

    driver = webdriver.Chrome(service=service, options=chrome_options)

    return driver


# ================= SCRAPER =================
def iniciar_scraper():

    global historico

    while True:

        driver = None

        try:

            print("🚀 Iniciando Betpawa Aviator")

            driver = start_driver()

            wait = WebDriverWait(driver, 40)

            driver.get(URL)

            time.sleep(10)

            # BOTÃO LOGIN
            try:
                btn_login = wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'Login')]"))
                )
                btn_login.click()
            except:
                pass

            time.sleep(5)

            # TELEFONE
            phone = wait.until(
                EC.presence_of_element_located((By.ID, "phoneNumber"))
            )

            phone.clear()

            for c in PHONE:
                phone.send_keys(c)
                time.sleep(0.05)

            time.sleep(2)

            # PIN
            pwd = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
            )

            pwd.clear()

            for c in PIN:
                pwd.send_keys(c)
                time.sleep(0.05)

            time.sleep(2)

            # SUBMIT LOGIN
            try:
                submit = driver.find_element(By.CSS_SELECTOR, "button[data-test-id='logInButton']")
                submit.click()
            except:
                pass

            time.sleep(10)

            # IFRAME DO JOGO
            iframe = wait.until(
                EC.presence_of_element_located((By.TAG_NAME, "iframe"))
            )

            driver.switch_to.frame(iframe)

            print("✅ Dentro do iframe Aviator")

            time.sleep(10)

            # LOOP DE HISTÓRICO
            while True:

                elements = driver.find_elements(By.CSS_SELECTOR, ".payout")

                novos = []

                for el in elements:

                    txt = el.text.strip()

                    if txt:

                        match = re.search(r'(\d+\.?\d*)', txt)

                        if match:
                            novos.append(float(match.group(1)))

                if novos and novos != historico:

                    historico = novos

                    print("📊 Histórico:", historico[:20])

                time.sleep(10)

        except Exception as e:

            print("🔥 ERRO:", e)

            time.sleep(15)

        finally:

            try:
                if driver:
                    driver.quit()
            except:
                pass


# ================= API =================

@app.route("/")
def home():
    return "✅ Betpawa Aviator rodando!"

@app.route("/api/history")
def get_history():
    return jsonify(historico)

@app.route("/api/last")
def get_last():
    return jsonify(historico[-1] if historico else None)


# ================= START =================

if __name__ == "__main__":

    threading.Thread(target=iniciar_scraper, daemon=True).start()

    port = int(os.environ.get("PORT", 8080))

    app.run(host="0.0.0.0", port=port)
