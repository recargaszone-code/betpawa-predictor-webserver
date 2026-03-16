# main.py (versão corrigida para evitar spam Telegram)
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
    TimeoutException, StaleElementReferenceException, WebDriverException
)

app = Flask(__name__)

# ================= CONFIG HARDCODED (ambiente de teste) =================
TELEGRAM_TOKEN = "8742776802:AAHSzD1qTwCqMEOdoW9_pT2l5GfmMBWUZQY"
TELEGRAM_CHAT_ID = "7427648935"
PHONE = "857789345"
PIN = "2010"
URL = "https://www.betpawa.co.mz/games?gameId=aviator&filter=all&redirectBack=/games"
# ======================================================================

historico = []          # snapshot atual da página (para detectar mudança)
global_history = []     # acumula até 50 (últimos 50)
_last_telegram = 0


def send_telegram_text(msg, throttle_seconds=6):
    """
    Envia texto ao Telegram com throttle customizável por chamada.
    throttle_seconds=0 => sem throttle (tentar enviar imediatamente).
    """
    global _last_telegram
    now = time.time()
    if throttle_seconds and (now - _last_telegram) < throttle_seconds:
        # não envia (throttled)
        return False
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
        _last_telegram = now
        return True
    except Exception:
        return False


def send_telegram_photo(path, caption="", throttle_seconds=30):
    global _last_telegram
    now = time.time()
    if (now - _last_telegram) < throttle_seconds:
        return False
    try:
        with open(path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                files={"photo": f},
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                timeout=30,
            )
        _last_telegram = now
        return True
    except Exception:
        return False


def screenshot_and_send(driver, label):
    try:
        path = "/tmp/print.png"
        driver.save_screenshot(path)
        send_telegram_photo(path, caption=f"📍 {label}", throttle_seconds=30)
    except Exception:
        pass


def safe_click(driver, element):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        element.click()
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
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
    except Exception:
        return False


def coletar_historico_dom(driver):
    out = []
    try:
        elems = driver.find_elements(By.CSS_SELECTOR, "div.payouts-block div.payout, div.payout")
        pat = re.compile(r"(\d+\.?\d*)")
        for e in elems:
            try:
                txt = e.text.strip()
                m = pat.search(txt)
                if m:
                    out.append(float(m.group(1)))
            except Exception:
                continue
    except Exception:
        pass
    return out


def page_shows_rate_limit(driver):
    try:
        return any(token in driver.page_source.lower() for token in ["rate limit", "too many requests", "429"])
    except Exception:
        return False


def iniciar_scraper():
    global historico, global_history
    backoff = 8
    max_backoff = 600
    last_heartbeat = 0
    HEARTBEAT_INTERVAL = 30 * 60  # 30 minutos (apenas se quiser heartbeat)

    while True:
        driver = None
        try:
            send_telegram_text("🟢 Iniciando BETPAWA Aviator (modo protegido)", throttle_seconds=0)
            time.sleep(5 + random.uniform(0, 5))

            opts = Options()
            # Usa headless se a variável de ambiente pedir (ou sempre no container)
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--window-size=1366,768")
            opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

            if os.path.exists("/usr/bin/chromium"):
                opts.binary_location = "/usr/bin/chromium"
            service = Service("/usr/bin/chromedriver") if os.path.exists("/usr/bin/chromedriver") else Service()

            driver = webdriver.Chrome(service=service, options=opts)
            wait = WebDriverWait(driver, 30)

            # PASSO 1
            send_telegram_text("📍 Abrindo URL do Betpawa", throttle_seconds=0)
            driver.get(URL)
            time.sleep(6)
            screenshot_and_send(driver, "1 - Página inicial aberta")

            # PASSO 2 - login modal
            try:
                login_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//button[@data-test-id='confirmation-modal-secondary-button' and contains(.,'Login')]")))
                safe_click(driver, login_btn)
                send_telegram_text("✅ Modal de Login aberto", throttle_seconds=0)
            except Exception:
                # modal pode já estar aberto — não enviar spam
                pass
            time.sleep(4)
            screenshot_and_send(driver, "2 - Após Login modal")

            # PASSO 3 - telefone
            try:
                phone = wait.until(EC.presence_of_element_located((By.ID, "phoneNumber")))
                js_set_value_and_dispatch(driver, phone, PHONE)
                send_telegram_text("✅ Telefone preenchido", throttle_seconds=0)
            except Exception:
                send_telegram_text("⚠️ Falha ao localizar/preencher telefone", throttle_seconds=0)
            time.sleep(4)
            screenshot_and_send(driver, "3 - Telefone OK")

            # PASSO 4 - pin
            try:
                pin = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "input[data-test-id='loginFormPasswordInput'], input[type='password']")))
                js_set_value_and_dispatch(driver, pin, PIN)
                send_telegram_text("✅ PIN preenchido", throttle_seconds=0)
            except Exception:
                send_telegram_text("⚠️ Falha ao localizar/preencher PIN", throttle_seconds=0)
            time.sleep(4)
            screenshot_and_send(driver, "4 - PIN OK")

            # PASSO 5 - submit login
            try:
                submit = driver.find_element(By.CSS_SELECTOR, "button[data-test-id='logInButton']")
                if submit.get_attribute("disabled"):
                    driver.execute_script("arguments[0].removeAttribute('disabled');", submit)
                safe_click(driver, submit)
                send_telegram_text("✅ Login enviado", throttle_seconds=0)
            except Exception:
                send_telegram_text("⚠️ Falha ao enviar Login (submit não encontrado)", throttle_seconds=0)
            time.sleep(6)
            screenshot_and_send(driver, "5 - Login enviado")

            # PASSO 6 - localizar iframe do jogo
            iframe_el = None
            start = time.time()
            while time.time() - start < 40:
                try:
                    for f in driver.find_elements(By.TAG_NAME, "iframe"):
                        src = (f.get_attribute("src") or "").lower()
                        if "launch.spribegaming.com" in src or "aviator-next.spribegaming.com" in src or "spribegaming" in src:
                            iframe_el = f
                            break
                    if iframe_el:
                        break
                except Exception:
                    pass
                time.sleep(1)
            if not iframe_el:
                raise RuntimeError("iframe do jogo não encontrado")
            driver.switch_to.frame(iframe_el)
            send_telegram_text("✅ Dentro do iframe do Aviator", throttle_seconds=0)
            time.sleep(4)
            screenshot_and_send(driver, "6 - Dentro do Aviator")

            # PASSO 7 - histórico inicial
            start = time.time()
            found = False
            while time.time() - start < 40:
                if page_shows_rate_limit(driver):
                    sleep_time = min(max_backoff, backoff) + random.uniform(0, 3)
                    send_telegram_text(f"⚠️ Rate limit detectado — dormindo {int(sleep_time)}s", throttle_seconds=0)
                    time.sleep(sleep_time)
                    continue
                vals = coletar_historico_dom(driver)
                if vals:
                    historico = vals[:]
                    global_history = vals[:]     # iniciar acumulador
                    send_telegram_text("✅ Histórico inicial carregado", throttle_seconds=0)
                    found = True
                    break
                time.sleep(2)
            if not found:
                send_telegram_text("⚠️ Histórico inicial não detectado (seguindo no loop)", throttle_seconds=0)

            # ============ LOOP PRINCIPAL ============
            while True:
                # heartbeat: enviar a cada HEARTBEAT_INTERVAL (opcional)
                now = time.time()
                if now - last_heartbeat > HEARTBEAT_INTERVAL:
                    send_telegram_text("💓 Heartbeat: scraper rodando", throttle_seconds=0)
                    last_heartbeat = now

                if page_shows_rate_limit(driver):
                    sleep_time = min(max_backoff, backoff) + random.uniform(0, 3)
                    send_telegram_text(f"⚠️ Rate limit detectado — dormindo {int(sleep_time)}s", throttle_seconds=0)
                    time.sleep(sleep_time)
                    continue

                novos = coletar_historico_dom(driver)
                if novos and (not historico or novos[0] != historico[0]):
                    added = False
                    # inserir novos não duplicados no topo
                    for v in novos:
                        if v not in global_history:
                            global_history.insert(0, v)
                            added = True
                    # manter apenas 50
                    if len(global_history) > 50:
                        global_history = global_history[:50]
                    if added:
                        lista = ", ".join(f"{v:.2f}x" for v in global_history[:25])
                        send_telegram_text(
                            f"📊 **BETPAWA AVIATOR - ÚLTIMOS {len(global_history)}**\n\n[{lista}]\n\nÚltimo: *{global_history[0]:.2f}x*",
                            throttle_seconds=6,
                        )
                        # screenshot ocasional
                        if random.random() < 0.45:
                            screenshot_and_send(driver, f"Histórico atualizado ({len(global_history)}/50)")
                    historico = novos[:]

                # --------------------------------------------------
                # REMOVED: envio de "Aguardando 10s para próxima verificação..."
                # Não enviar esse tipo de mensagem repetitiva para evitar flood.
                # --------------------------------------------------

                time.sleep(10)

        except Exception as e:
            # mensagem de erro com throttle zero (queremos ser notificados)
            send_telegram_text(f"🔥 ERRO SCRAPER: {type(e).__name__} - {e}", throttle_seconds=0)
            traceback.print_exc()
            sleep_time = min(max_backoff, backoff) + random.uniform(1, 4)
            time.sleep(sleep_time)
            backoff = min(max_backoff, backoff * 2)

        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            time.sleep(5)


@app.route("/api/history")
def api_history():
    return jsonify(global_history)


@app.route("/api/last")
def api_last():
    return jsonify(global_history[0] if global_history else None)


@app.route("/")
def home():
    return "BETPAWA AVIATOR - Histórico acumulado até 50 (remove o mais antigo)"


if __name__ == "__main__":
    threading.Thread(target=iniciar_scraper, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
