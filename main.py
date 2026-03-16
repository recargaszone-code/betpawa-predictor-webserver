#!/usr/bin/env python3
# main.py — BETPAWA Aviator scraper (robusto, stealth, backoff, telegram throttle)

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
    Retorna True se enviar com sucesso, False caso throttled ou falha.
    """
    global _last_telegram
    now = time.time()
    if throttle_seconds and (now - _last_telegram) < throttle_seconds:
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
            try{el.blur();}catch(e){}
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
        body = driver.page_source.lower()
        # tokens comuns
        return any(token in body for token in ["rate limit", "too many requests", "429", "rate-limited", "rate_limited", "too many requests"])
    except Exception:
        return False


# ---------- START DRIVER ----------
def start_driver():
    """
    Inicia o Chrome/Chromium com flags 'stealth' e injeta script via CDP para reduzir fingerprint.
    """
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1366,768")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    )

    if os.path.exists("/usr/bin/chromium"):
        chrome_options.binary_location = "/usr/bin/chromium"

    service = Service("/usr/bin/chromedriver") if os.path.exists("/usr/bin/chromedriver") else Service()

    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        stealth_script = r"""
        // basic stealth: remove webdriver and normalize some fingerprint values
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        try { Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR','pt']}); } catch(e){}
        try { Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4]}); } catch(e){}
        const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
        if(originalQuery){
            try{
                window.navigator.permissions.query = (parameters)=> {
                    if(parameters && parameters.name === 'notifications'){
                        return Promise.resolve({ state: Notification.permission });
                    }
                    return originalQuery(parameters);
                };
            }catch(e){}
        }
        try{
            window.navigator.__defineGetter__('userAgent', function(){
                return 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36';
            });
        }catch(e){}
        """
        # addScriptToEvaluateOnNewDocument may fail depending on driver — ignore if so
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stealth_script})
    except Exception:
        pass

    # small settle
    time.sleep(0.4)
    return driver
# ---------- END START DRIVER ----------


# ---------- INICIAR SCRAPER ----------
def iniciar_scraper():
    global historico, global_history
    base_backoff = 8       # segundos iniciais
    max_backoff = 600      # 10 minutos
    backoff = base_backoff
    consecutive_rate_limits = 0
    RATE_LIMIT_RESET_AFTER = 6   # reinicia driver se ocorrer X rate limits consec
    # adaptive polling parameters (more conservative than before)
    MIN_POLL = 8
    MAX_POLL = 18
    SCREENSHOT_PROB = 0.25

    HEARTBEAT_INTERVAL = 30 * 60  # opcional: 30 minutos

    last_heartbeat = 0

    while True:
        driver = None
        try:
            send_telegram_text("🟢 Iniciando BETPAWA Aviator (modo protegido)", throttle_seconds=0)
            time.sleep(3 + random.uniform(1, 5))

            driver = start_driver()
            wait = WebDriverWait(driver, 30)

            # abrir URL
            send_telegram_text("📍 Abrindo URL do Betpawa", throttle_seconds=0)
            driver.get(URL)
            time.sleep(6 + random.uniform(0.5, 3.0))
            screenshot_and_send(driver, "Página inicial aberta")

            # modal login: tentar abrir
            try:
                login_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//button[@data-test-id='confirmation-modal-secondary-button' and contains(.,'Login')]")),)
                safe_click(driver, login_btn)
                time.sleep(1 + random.random()*1.8)
            except Exception:
                # modal pode já estar aberto; não é fatal
                pass

            # preencher telefone
            try:
                phone = wait.until(EC.presence_of_element_located((By.ID, "phoneNumber")), timeout=8)
                js_set_value_and_dispatch(driver, phone, PHONE)
                send_telegram_text("✅ Telefone preenchido", throttle_seconds=0)
            except Exception:
                send_telegram_text("⚠️ Não encontrei input de telefone", throttle_seconds=0)

            time.sleep(0.8 + random.random()*1.6)

            # preencher PIN
            try:
                pin = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "input[data-test-id='loginFormPasswordInput'], input[type='password']")), timeout=8)
                js_set_value_and_dispatch(driver, pin, PIN)
                send_telegram_text("✅ PIN preenchido", throttle_seconds=0)
            except Exception:
                send_telegram_text("⚠️ Não encontrei input de PIN", throttle_seconds=0)

            time.sleep(0.6 + random.random()*1.2)

            # submeter login
            try:
                submit = driver.find_element(By.CSS_SELECTOR, "button[data-test-id='logInButton']")
                if submit.get_attribute("disabled"):
                    driver.execute_script("arguments[0].removeAttribute('disabled');", submit)
                safe_click(driver, submit)
                send_telegram_text("✅ Login enviado", throttle_seconds=0)
            except Exception:
                send_telegram_text("⚠️ Falha ao enviar login (submit não encontrado)", throttle_seconds=0)

            time.sleep(4 + random.uniform(1, 3))
            screenshot_and_send(driver, "Login enviado / aguardando iframe")

            # localizar iframe do jogo
            iframe_el = None
            start = time.time()
            while time.time() - start < 45:
                try:
                    frames = driver.find_elements(By.TAG_NAME, "iframe")
                    for f in frames:
                        try:
                            src = (f.get_attribute("src") or "").lower()
                            if "spribegaming" in src or "aviator" in src or "launch.spribe" in src:
                                iframe_el = f
                                break
                        except Exception:
                            continue
                    if iframe_el:
                        break
                except Exception:
                    pass
                time.sleep(1 + random.random()*0.6)

            if not iframe_el:
                raise RuntimeError("iframe do jogo não encontrado (timeout)")

            # trocar para iframe
            try:
                driver.switch_to.frame(iframe_el)
            except Exception:
                # cross-origin ou outra proteção — reiniciar
                raise RuntimeError("Falha ao trocar para iframe (possível cross-origin)")

            send_telegram_text("✅ Dentro do iframe do Aviator", throttle_seconds=0)
            time.sleep(2 + random.random()*2)
            screenshot_and_send(driver, "Dentro do Aviator")

            # histórico inicial
            start = time.time()
            found = False
            while time.time() - start < 45:
                if page_shows_rate_limit(driver):
                    consecutive_rate_limits += 1
                    sleep_time = min(max_backoff, backoff) + random.uniform(0.5, 2.0)
                    send_telegram_text(f"⚠️ Rate limit detectado — dormindo {int(sleep_time)}s", throttle_seconds=0)
                    time.sleep(sleep_time)
                    backoff = min(max_backoff, backoff * 2)
                    continue
                vals = coletar_historico_dom(driver)
                if vals:
                    historico = vals[:]
                    global_history = vals[:]  # inicia acumulador
                    send_telegram_text("✅ Histórico inicial carregado", throttle_seconds=0)
                    found = True
                    backoff = base_backoff = 8
                    consecutive_rate_limits = 0
                    break
                time.sleep(2 + random.random()*0.8)
            if not found:
                send_telegram_text("⚠️ Histórico inicial não detectado — seguindo no loop", throttle_seconds=0)

            # loop principal (adaptive polling)
            while True:
                # heartbeat opcional
                now = time.time()
                if now - last_heartbeat > HEARTBEAT_INTERVAL:
                    send_telegram_text("💓 Heartbeat: scraper rodando", throttle_seconds=0)
                    last_heartbeat = now

                if page_shows_rate_limit(driver):
                    consecutive_rate_limits += 1
                    sleep_time = min(max_backoff, backoff) + random.uniform(1.0, 4.0)
                    send_telegram_text(f"⚠️ Rate limit detectado — dormindo {int(sleep_time)}s", throttle_seconds=0)
                    time.sleep(sleep_time)
                    backoff = min(max_backoff, backoff * 2)
                    if consecutive_rate_limits >= RATE_LIMIT_RESET_AFTER:
                        send_telegram_text("🔄 Muitos rate-limits consecutivos — reiniciando driver", throttle_seconds=0)
                        raise RuntimeError("Rate limit persistente - reiniciar driver")
                    continue

                try:
                    novos = coletar_historico_dom(driver)
                except WebDriverException:
                    raise RuntimeError("WebDriverException durante coleta (reiniciar driver)")

                if novos and (not historico or novos[0] != historico[0]):
                    added = False
                    for v in novos:
                        if v not in global_history:
                            global_history.insert(0, v)
                            added = True
                    if len(global_history) > 50:
                        global_history = global_history[:50]
                    if added:
                        lista = ", ".join(f"{v:.2f}x" for v in global_history[:25])
                        send_telegram_text(
                            f"📊 BETPAWA AVIATOR — ÚLTIMOS {len(global_history)}\n[{lista}]\nÚltimo: *{global_history[0]:.2f}x*",
                            throttle_seconds=6
                        )
                        if random.random() < SCREENSHOT_PROB:
                            screenshot_and_send(driver, f"Histórico atualizado ({len(global_history)}/50)")
                    historico = novos[:]
                    # reduza backoff após sucesso
                    backoff = base_backoff
                    consecutive_rate_limits = 0

                # adaptive sleep
                poll = MIN_POLL + random.uniform(0, MAX_POLL - MIN_POLL)
                if consecutive_rate_limits > 0:
                    poll = min(MAX_POLL, poll + consecutive_rate_limits * 4)
                time.sleep(poll)

        except Exception as e:
            send_telegram_text(f"🔥 ERRO SCRAPER: {type(e).__name__} - {e}", throttle_seconds=0)
            traceback.print_exc()
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
            # escalate backoff and sleep
            backoff = min(max_backoff, backoff * 2) if 'backoff' in locals() else base_backoff
            sleep_time = min(max_backoff, backoff) + random.uniform(2, 6)
            time.sleep(sleep_time)
            consecutive_rate_limits = 0

        finally:
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
            time.sleep(3)
# ---------- END INICIAR SCRAPER ----------


# Flask routes
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
    # Inicia scraper em thread background e serve Flask
    threading.Thread(target=iniciar_scraper, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    # Permitir que Flask escute em todas as interfaces (container)
    app.run(host="0.0.0.0", port=port)
