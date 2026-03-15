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

# ================= CONFIG HARDCODED (BetPawa - Railway) =================
TELEGRAM_TOKEN = "8742776802:AAHSzD1qTwCqMEOdoW9_pT2l5GfmMBWUZQY"
TELEGRAM_CHAT_ID = "7427648935"
PHONE = "857789345"
PIN = "2010"
URL = "https://www.betpawa.co.mz/games?gameId=aviator&filter=all&redirectBack=/games"
# =====================================================================

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
    except Exception:
        pass


def send_telegram_photo(path, caption=""):
    global _last_telegram
    if time.time() - _last_telegram < 30:
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
    except Exception:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            return False


def js_set_value_and_dispatch(driver, element, value):
    try:
        driver.execute_script("""
            const el = arguments[0];
            const val = arguments[1];
            try{ el.focus(); }catch(e){}
            try{
                if(el.shadowRoot){
                    const shadowInput = el.shadowRoot.querySelector('input');
                    if(shadowInput){
                        shadowInput.value = val;
                        shadowInput.dispatchEvent(new Event('input',{bubbles:true}));
                        shadowInput.dispatchEvent(new Event('change',{bubbles:true}));
                    }
                }
            }catch(e){}
            try{ el.value = val; }catch(e){}
            try{ el.setAttribute('value', val); }catch(e){}
            try{ el.dispatchEvent(new Event('input', {bubbles:true})); }catch(e){}
            try{ el.dispatchEvent(new Event('change', {bubbles:true})); }catch(e){}
            try{ el.blur(); }catch(e){}
            return true;
        """, element, value)
        return True
    except Exception:
        return False


def find_element_variants(driver, by_sel_list, timeout=4):
    wait = WebDriverWait(driver, timeout)
    for by, sel in by_sel_list:
        try:
            el = wait.until(EC.presence_of_element_located((by, sel)))
            if el:
                return el
        except Exception:
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
                if not txt:
                    continue
                m = pat.search(txt)
                if m:
                    out.append(float(m.group(1)))
            except StaleElementReferenceException:
                continue
            except Exception:
                continue
    except Exception:
        pass
    return out


def page_shows_rate_limit(driver):
    try:
        body = driver.page_source.lower()
        checks = ["rate limit", "too many requests", "429", "rate-limited", "try again later"]
        return any(token in body for token in checks)
    except Exception:
        return False


def iniciar_scraper():
    global historico
    backoff = 8
    max_backoff = 600

    while True:
        driver = None
        try:
            send_telegram_text("🟢 Iniciando BETPAWA Aviator (Railway mode)...")

            opts = Options()
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--window-size=1366,768")
            opts.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
            )
            if os.path.exists("/usr/bin/chromium"):
                opts.binary_location = "/usr/bin/chromium"
            service = Service("/usr/bin/chromedriver") if os.path.exists("/usr/bin/chromedriver") else Service()

            driver = webdriver.Chrome(service=service, options=opts)
            wait = WebDriverWait(driver, 30)

            send_telegram_text("📄 Abrindo BetPawa...")
            driver.get(URL)
            time.sleep(6)
            screenshot_and_send(driver, "Página inicial aberta")

            # 1) Botão Login modal
            try:
                login_modal_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//button[@data-test-id='confirmation-modal-secondary-button' and contains(.,'Login')]")
                ))
                safe_click(driver, login_modal_btn)
                time.sleep(1)
                send_telegram_text("✅ Botão Login modal clicado")
            except TimeoutException:
                send_telegram_text("ℹ️ Modal Login não apareceu (talvez já logado)")

            # 2) Telefone
            phone_elem = None
            try:
                phone_elem = wait.until(EC.presence_of_element_located((By.ID, "phoneNumber")))
            except Exception:
                phone_elem = find_element_variants(driver, [
                    (By.CSS_SELECTOR, "input[data-test-id='loginFormPhoneNumberInput']"),
                    (By.CSS_SELECTOR, "input[inputmode='numeric']"),
                    (By.XPATH, "//input[@name='username' or @name='phone' or contains(@id,'phone')]"),
                ])

            if phone_elem:
                js_set_value_and_dispatch(driver, phone_elem, PHONE)
                send_telegram_text("✅ Telefone preenchido")
            else:
                screenshot_and_send(driver, "❌ Sem campo telefone")

            time.sleep(0.5)

            # 3) PIN
            pwd_elem = None
            try:
                pwd_elem = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "input[data-test-id='loginFormPasswordInput'], input[type='password']")
                ))
            except Exception:
                pass

            if pwd_elem:
                js_set_value_and_dispatch(driver, pwd_elem, PIN)
                send_telegram_text("✅ PIN preenchido")
            else:
                screenshot_and_send(driver, "❌ Sem campo PIN")

            time.sleep(0.5)

            # 4) Botão Log In
            try:
                login_submit = driver.find_element(By.CSS_SELECTOR, "button[data-test-id='logInButton']")
                if login_submit.get_attribute("disabled"):
                    driver.execute_script("arguments[0].removeAttribute('disabled');", login_submit)
                safe_click(driver, login_submit)
                screenshot_and_send(driver, "Login enviado")
                send_telegram_text("✅ Login enviado")
            except Exception:
                screenshot_and_send(driver, "❌ Erro botão Log In")

            time.sleep(6)
            send_telegram_text("🔄 Aguardando iframe Spribe...")

            # 5) Iframe
            iframe_el = None
            start = time.time()
            while time.time() - start < 30:
                candidates = driver.find_elements(By.TAG_NAME, "iframe")
                for f in candidates:
                    src = (f.get_attribute("src") or "").lower()
                    if "spribegaming" in src or "aviator" in src:
                        iframe_el = f
                        break
                if iframe_el:
                    break
                time.sleep(1)

            if not iframe_el:
                screenshot_and_send(driver, "❌ Sem iframe")
                raise RuntimeError("iframe não localizado")

            try:
                driver.switch_to.frame(iframe_el)
                send_telegram_text("✅ Entrou no iframe Spribe")
            except Exception:
                src = iframe_el.get_attribute("src")
                driver.switch_to.default_content()
                driver.execute_script("window.open(arguments[0]);", src)
                driver.switch_to.window(driver.window_handles[-1])
                time.sleep(3)
                send_telegram_text("✅ Iframe aberto em nova aba")

            # Aguarda payouts iniciais
            send_telegram_text("⏳ Aguardando histórico aparecer...")
            start = time.time()
            while time.time() - start < 30:
                if page_shows_rate_limit(driver):
                    sleep_time = min(max_backoff, backoff) + random.uniform(0.5, 2)
                    send_telegram_text(f"Rate limit detectado no loop — dormindo {int(sleep_time)}s")
                    time.sleep(sleep_time)
                    continue
                vals = coletar_historico_dom(driver)
                if vals:
                    historico = vals
                    send_telegram_text("✅ Histórico inicial detectado")
                    break
                time.sleep(1)

            # ================= LOOP PRINCIPAL DE MONITORAMENTO =================
            while True:
                if page_shows_rate_limit(driver):
                    sleep_time = min(max_backoff, backoff) + random.uniform(0.5, 2)
                    send_telegram_text(f"Rate limit detectado no loop — dormindo {int(sleep_time)}s")
                    time.sleep(sleep_time)
                    backoff = min(max_backoff, backoff * 2)
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
                        if random.random() < 0.5:
                            screenshot_and_send(driver, "Histórico atualizado")
                except StaleElementReferenceException:
                    time.sleep(1)
                except WebDriverException:
                    # Tenta recuperar iframe (exatamente como no código original)
                    try:
                        driver.switch_to.default_content()
                        frames = driver.find_elements(By.TAG_NAME, "iframe")
                        for f in frames:
                            src = (f.get_attribute("src") or "").lower()
                            if "spribegaming" in src or "aviator" in src:
                                driver.switch_to.frame(f)
                                break
                    except Exception:
                        raise
                except Exception as inner:
                    raise inner

                time.sleep(5 + random.uniform(0, 2))

        except Exception as e:
            print("ERRO principal:", type(e).__name__, e)
            traceback.print_exc()

            sleep_time = min(max_backoff, backoff) + random.uniform(1, 3)
            send_telegram_text(f"ERRO: {type(e).__name__} → reiniciando em {int(sleep_time)}s")

            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
            driver = None

            time.sleep(sleep_time)
            backoff = min(max_backoff, backoff * 2)

        finally:
            time.sleep(3)


@app.route("/api/history")
def api_history():
    return jsonify(historico)


@app.route("/api/last")
def api_last():
    return jsonify(historico[0] if historico else None)


@app.route("/")
def home():
    return "BETPAWA AVIATOR BOT (Railway - 100% baseado no código local)"


if __name__ == "__main__":
    threading.Thread(target=iniciar_scraper, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
