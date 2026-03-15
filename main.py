import os
import time
import threading
import re
import random
import traceback
import requests
from flask import Flask, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
    WebDriverException,
)

app = Flask(__name__)

# ================= CONFIG HARDCODED (BetPawa) =================
TELEGRAM_TOKEN = "8742776802:AAHSzD1qTwCqMEOdoW9_pT2l5GfmMBWUZQY"
TELEGRAM_CHAT_ID = "7427648935"
PHONE = "857789345"
PIN = "2010"
URL = "https://www.betpawa.co.mz/games?gameId=aviator&filter=all&redirectBack=/games"
# ============================================================

historico = []
_last_telegram = 0


def send_telegram_text(msg, throttle_seconds=6):
    global _last_telegram
    if time.time() - _last_telegram < throttle_seconds:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=15,
        )
        _last_telegram = time.time()
    except Exception as e:
        print("Falha Telegram text:", e)


def send_telegram_photo(path, caption="", throttle_seconds=30):
    global _last_telegram
    if time.time() - _last_telegram < throttle_seconds:
        return
    try:
        with open(path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                files={"photo": f},
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                timeout=30,
            )
        _last_telegram = time.time()
    except Exception as e:
        print("Falha Telegram photo:", e)


def screenshot_and_send(driver, label):
    try:
        path = "/tmp/print.png"
        driver.save_screenshot(path)
        send_telegram_photo(path, caption=f"📸 {label}")
    except Exception as e:
        print("Erro screenshot:", e)


def safe_click(driver, element):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        element.click()
        return True
    except:
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except:
            return False


def js_set_value_and_dispatch(driver, element, value):
    try:
        driver.execute_script("""
            const el = arguments[0]; const val = arguments[1];
            try{el.focus();}catch(e){}
            try{el.value=val;}catch(e){}
            try{el.setAttribute('value',val);}catch(e){}
            try{el.dispatchEvent(new Event('input',{bubbles:true}));}catch(e){}
            try{el.dispatchEvent(new Event('change',{bubbles:true}));}catch(e){}
            return true;
        """, element, value)
        return True
    except:
        return False


def safe_find_elements(driver, selector):
    for _ in range(4):
        try:
            return driver.find_elements(By.CSS_SELECTOR, selector)
        except StaleElementReferenceException:
            time.sleep(0.3)
            continue
        except:
            break
    return []


def coletar_historico_dom(driver):
    items = safe_find_elements(driver, ".payouts-block .payout, .payout")
    vals = []
    pat = re.compile(r"(\d+(\.\d+)?)")
    for el in items:
        try:
            txt = el.text.strip()
            m = pat.search(txt)
            if m:
                vals.append(float(m.group(1)))
        except:
            continue
    return vals


def page_shows_rate_limit(driver):
    try:
        body = driver.page_source.lower()
        checks = ["rate limit", "too many requests", "429", "rate-limited", "try again later"]
        return any(token in body for token in checks)
    except:
        return False


def iniciar_scraper():
    global historico
    backoff = 8
    max_backoff = 600

    while True:
        driver = None
        try:
            print("=== BETPAWA Aviator iniciando (Railway) ===")
            send_telegram_text("🟢 Iniciando BETPAWA Aviator (Railway mode)...")

            opts = Options()
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--window-size=1366,768")
            opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36")

            if os.path.exists("/usr/bin/chromium"):
                opts.binary_location = "/usr/bin/chromium"
            service = Service("/usr/bin/chromedriver") if os.path.exists("/usr/bin/chromedriver") else Service()

            driver = webdriver.Chrome(service=service, options=opts)
            wait = WebDriverWait(driver, 30)

            driver.get(URL)
            time.sleep(6)
            screenshot_and_send(driver, "Página BetPawa aberta")

            # ================= LOGIN =================
            # 1. Modal Login
            try:
                modal_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//button[@data-test-id='confirmation-modal-secondary-button' and contains(.,'Login')]")
                ))
                safe_click(driver, modal_btn)
                time.sleep(1)
            except TimeoutException:
                pass

            # 2. Telefone
            try:
                phone_el = wait.until(EC.presence_of_element_located((By.ID, "phoneNumber")))
                js_set_value_and_dispatch(driver, phone_el, PHONE)
            except:
                screenshot_and_send(driver, "❌ Sem campo telefone")

            # 3. PIN
            try:
                pin_el = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "input[data-test-id='loginFormPasswordInput'], input[type='password']")
                ))
                js_set_value_and_dispatch(driver, pin_el, PIN)
            except:
                screenshot_and_send(driver, "❌ Sem campo PIN")

            # 4. Submit
            try:
                submit = driver.find_element(By.CSS_SELECTOR, "button[data-test-id='logInButton']")
                if submit.get_attribute("disabled"):
                    driver.execute_script("arguments[0].removeAttribute('disabled');", submit)
                safe_click(driver, submit)
                screenshot_and_send(driver, "Login enviado")
            except:
                screenshot_and_send(driver, "❌ Erro no botão Log In")

            time.sleep(6)

            # ================= IFRAME =================
            iframe_el = None
            for _ in range(25):
                for f in driver.find_elements(By.TAG_NAME, "iframe"):
                    src = (f.get_attribute("src") or "").lower()
                    if "spribegaming" in src or "aviator" in src:
                        iframe_el = f
                        break
                if iframe_el:
                    break
                time.sleep(1)

            if iframe_el:
                try:
                    driver.switch_to.frame(iframe_el)
                    print("✅ Entrou no iframe Spribe")
                except:
                    # fallback nova aba
                    src = iframe_el.get_attribute("src")
                    driver.switch_to.default_content()
                    driver.execute_script("window.open(arguments[0]);", src)
                    driver.switch_to.window(driver.window_handles[-1])
                    time.sleep(3)

            # ================= AGUARDAR PAYOUTS =================
            print("Aguardando payouts aparecerem...")
            start_wait = time.time()
            while True:
                if page_shows_rate_limit(driver):
                    sleep_time = min(max_backoff, backoff) + random.uniform(0.5, 2)
                    send_telegram_text(f"⚠️ Rate limit detectado — dormindo {int(sleep_time)}s")
                    time.sleep(sleep_time)
                    backoff = min(max_backoff, backoff * 2)
                    continue

                if safe_find_elements(driver, ".payouts-block .payout, .payout"):
                    break

                if time.time() - start_wait > 90:
                    send_telegram_text("⚠️ Ainda sem payouts após 90s...")
                    time.sleep(min(max_backoff, backoff))
                    backoff = min(max_backoff, backoff * 2)
                    start_wait = time.time()

                time.sleep(2)

            backoff = 8
            send_telegram_text("🚀 BETPAWA Aviator conectado com sucesso!")
            screenshot_and_send(driver, "Dentro do jogo - payouts OK")

            historico = coletar_historico_dom(driver)

            # ================= LOOP DE MONITORAMENTO =================
            while True:
                if page_shows_rate_limit(driver):
                    sleep_time = min(max_backoff, backoff) + random.uniform(0.5, 2)
                    send_telegram_text(f"⚠️ Rate limit detectado no loop — dormindo {int(sleep_time)}s")
                    time.sleep(sleep_time)
                    continue

                try:
                    novos = coletar_historico_dom(driver)
                    if novos and novos != historico:
                        historico = novos
                        lista = ", ".join(f"{v:.2f}x" for v in historico[:20])
                        send_telegram_text(
                            f"📊 **BETPAWA AVIATOR**\n\n[{lista}]\n\nÚltimo: *{historico[0]:.2f}x*",
                            throttle_seconds=8
                        )
                        if random.random() < 0.6:
                            screenshot_and_send(driver, "Histórico atualizado")
                except StaleElementReferenceException:
                    time.sleep(1)
                except WebDriverException as e:
                    send_telegram_text(f"⚠️ WebDriverException: {str(e)[:200]}")
                    break

                time.sleep(5 + random.uniform(0, 2))

        except Exception as e:
            print("ERRO GERAL:", type(e).__name__, e)
            traceback.print_exc()
            try:
                send_telegram_text(f"🔥 ERRO BETPAWA: {type(e).__name__} - {str(e)[:150]}")
            except:
                pass

            sleep_time = min(max_backoff, backoff) + random.uniform(1, 3)
            time.sleep(sleep_time)
            backoff = min(max_backoff, backoff * 2)

        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            time.sleep(3)


@app.route("/api/history")
def api_history():
    return jsonify(historico)


@app.route("/api/last")
def api_last():
    return jsonify(historico[0] if historico else None)


@app.route("/")
def home():
    return "BETPAWA AVIATOR BOT (Railway protected mode)"


if __name__ == "__main__":
    threading.Thread(target=iniciar_scraper, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
