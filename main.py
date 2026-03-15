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
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)

app = Flask(__name__)

# ================= CONFIG HARDCODED =================
TELEGRAM_TOKEN = "8742776802:AAHSzD1qTwCqMEOdoW9_pT2l5GfmMBWUZQY"
TELEGRAM_CHAT_ID = "7427648935"
PHONE = "857789345"
PIN = "2010"
URL = "https://www.betpawa.co.mz/games?gameId=aviator&filter=all&redirectBack=/games"
# ===================================================

historico = []
_last_telegram = 0


def send_telegram_text(msg):
    global _last_telegram
    # throttle mínimo para não floodar, mas ainda envia quase tudo
    if time.time() - _last_telegram < 3:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
        _last_telegram = time.time()
    except Exception:
        pass


def send_telegram_photo(path, caption=""):
    global _last_telegram
    if time.time() - _last_telegram < 20:
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
    except Exception:
        pass


def screenshot_and_send(driver, label):
    try:
        path = "/tmp/print.png"
        driver.save_screenshot(path)
        send_telegram_photo(path, caption=f"📸 {label}")
    except Exception:
        pass


def safe_click(driver, element):
    try:
        element.click()
        return True
    except:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
            driver.execute_script("arguments[0].click();", element)
            return True
        except:
            return False


def js_set_value_and_dispatch(driver, element, value):
    try:
        driver.execute_script("""
            const el = arguments[0]; const val = arguments[1];
            try{el.focus();}catch(e){}
            try{if(el.shadowRoot){const si=el.shadowRoot.querySelector('input');if(si){si.value=val;si.dispatchEvent(new Event('input',{bubbles:true}));si.dispatchEvent(new Event('change',{bubbles:true}));}}}catch(e){}
            try{el.value=val;}catch(e){}
            try{el.setAttribute('value',val);}catch(e){}
            try{el.dispatchEvent(new Event('input',{bubbles:true}));}catch(e){}
            try{el.dispatchEvent(new Event('change',{bubbles:true}));}catch(e){}
            return true;
        """, element, value)
        return True
    except:
        return False


def find_element_variants(driver, by_sel_list, timeout=4):
    wait = WebDriverWait(driver, timeout)
    for by, sel in by_sel_list:
        try:
            return wait.until(EC.presence_of_element_located((by, sel)))
        except:
            continue
    return None


def coletar_historico_dom(driver):
    out = []
    try:
        elems = driver.find_elements(By.CSS_SELECTOR, ".payouts-block .payout, .payout")
        pat = re.compile(r"(\d+(\.\d+)?)")
        for e in elems:
            try:
                txt = e.text.strip()
                m = pat.search(txt)
                if m:
                    out.append(float(m.group(1)))
            except:
                continue
    except:
        pass
    return out


def page_shows_rate_limit(driver):
    try:
        return any(token in driver.page_source.lower() for token in ["rate limit", "too many requests", "429", "rate-limited", "try again later"])
    except:
        return False


def iniciar_scraper():
    global historico
    backoff = 8
    max_backoff = 600

    while True:
        driver = None
        try:
            send_telegram_text("🟢 Iniciando BETPAWA Aviator Railway...")
            time.sleep(10)

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

            send_telegram_text("📄 Abrindo URL BetPawa...")
            driver.get(URL)
            time.sleep(10)
            screenshot_and_send(driver, "Página inicial aberta")
            send_telegram_text("✅ Página carregada")

            # LOGIN MODAL
            try:
                send_telegram_text("🔘 Aguardando botão Login modal...")
                login_modal_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@data-test-id='confirmation-modal-secondary-button' and contains(.,'Login')]")))
                safe_click(driver, login_modal_btn)
                send_telegram_text("✅ Botão Login modal clicado")
            except:
                send_telegram_text("ℹ️ Modal não apareceu (talvez já logado)")
            time.sleep(10)

            # TELEFONE
            send_telegram_text("📱 Procurando campo telefone...")
            phone_elem = None
            try:
                phone_elem = wait.until(EC.presence_of_element_located((By.ID, "phoneNumber")))
            except:
                phone_elem = find_element_variants(driver, [
                    (By.CSS_SELECTOR, "input[data-test-id='loginFormPhoneNumberInput']"),
                    (By.CSS_SELECTOR, "input[inputmode='numeric']"),
                    (By.XPATH, "//input[contains(@id,'phone')]"),
                ])
            if phone_elem:
                js_set_value_and_dispatch(driver, phone_elem, PHONE)
                send_telegram_text("✅ Telefone preenchido")
            else:
                screenshot_and_send(driver, "❌ Sem campo telefone")
            time.sleep(10)

            # PIN
            send_telegram_text("🔑 Procurando campo PIN...")
            pwd_elem = None
            try:
                pwd_elem = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[data-test-id='loginFormPasswordInput'], input[type='password']")))
            except:
                pass
            if pwd_elem:
                js_set_value_and_dispatch(driver, pwd_elem, PIN)
                send_telegram_text("✅ PIN preenchido")
            else:
                screenshot_and_send(driver, "❌ Sem campo PIN")
            time.sleep(10)

            # SUBMIT LOGIN
            send_telegram_text("🔘 Clicando botão Log In...")
            try:
                login_submit = driver.find_element(By.CSS_SELECTOR, "button[data-test-id='logInButton']")
                if login_submit.get_attribute("disabled"):
                    driver.execute_script("arguments[0].removeAttribute('disabled');", login_submit)
                safe_click(driver, login_submit)
                screenshot_and_send(driver, "Login enviado")
                send_telegram_text("✅ Login enviado com sucesso")
            except:
                screenshot_and_send(driver, "❌ Erro no botão Log In")
            time.sleep(10)

            # IFRAME
            send_telegram_text("🖼️ Aguardando iframe Spribe...")
            iframe_el = None
            start = time.time()
            while time.time() - start < 40:
                for f in driver.find_elements(By.TAG_NAME, "iframe"):
                    if "spribegaming" in (f.get_attribute("src") or "").lower() or "aviator" in (f.get_attribute("src") or "").lower():
                        iframe_el = f
                        break
                if iframe_el:
                    break
                time.sleep(2)
            if iframe_el:
                try:
                    driver.switch_to.frame(iframe_el)
                    send_telegram_text("✅ Entrou no iframe Spribe")
                except:
                    src = iframe_el.get_attribute("src")
                    driver.switch_to.default_content()
                    driver.execute_script("window.open(arguments[0]);", src)
                    driver.switch_to.window(driver.window_handles[-1])
                    send_telegram_text("✅ Iframe aberto em nova aba")
            else:
                screenshot_and_send(driver, "❌ Sem iframe")
                raise RuntimeError("iframe não encontrado")
            time.sleep(10)

            # AGUARDANDO HISTÓRICO
            send_telegram_text("⏳ Aguardando histórico de payouts...")
            start = time.time()
            while time.time() - start < 40:
                if page_shows_rate_limit(driver):
                    sleep_time = min(max_backoff, backoff) + random.uniform(0, 3)
                    send_telegram_text(f"Rate limit detectado no loop — dormindo {int(sleep_time)}s")
                    time.sleep(sleep_time)
                    continue
                vals = coletar_historico_dom(driver)
                if vals:
                    historico = vals
                    send_telegram_text("✅ Histórico inicial detectado!")
                    break
                time.sleep(5)
            time.sleep(10)

            # ================= LOOP PRINCIPAL (cada atualização a cada 10s) =================
            while True:
                if page_shows_rate_limit(driver):
                    sleep_time = min(max_backoff, backoff) + random.uniform(0, 3)
                    send_telegram_text(f"Rate limit detectado no loop — dormindo {int(sleep_time)}s")
                    time.sleep(sleep_time)
                    continue

                try:
                    novos = coletar_historico_dom(driver)
                    if novos and novos != historico:
                        historico = novos
                        lista = ", ".join(f"{v:.2f}x" for v in historico[:20])
                        send_telegram_text(f"📊 **BETPAWA AVIATOR**\n\n[{lista}]\n\nÚltimo: *{historico[0]:.2f}x*")
                        if random.random() < 0.5:
                            screenshot_and_send(driver, "Histórico atualizado")
                except StaleElementReferenceException:
                    send_telegram_text("🔄 Stale Element — recuperando...")
                    time.sleep(5)
                except WebDriverException:
                    raise
                except Exception:
                    raise

                send_telegram_text("⏱️ Aguardando próxima verificação...")
                time.sleep(10)   # ← exatamente 10 segundos entre cada checagem

        except Exception as e:
            sleep_time = min(max_backoff, backoff) + random.uniform(1, 4)
            send_telegram_text(f"ERRO: {type(e).__name__} → reiniciando em {int(sleep_time)}s")
            time.sleep(sleep_time)
            backoff = min(max_backoff, backoff * 2)

        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            time.sleep(5)


@app.route("/api/history")
def api_history():
    return jsonify(historico)


@app.route("/")
def home():
    return "BETPAWA AVIATOR - Tudo logado no Telegram (10s por passo)"


if __name__ == "__main__":
    threading.Thread(target=iniciar_scraper, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
