# main.py - container-ready (deploy em Railway / VPS com Docker)
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
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
    WebDriverException,
)
from selenium.webdriver.support.ui import WebDriverWait

# fallback download driver
from webdriver_manager.chrome import ChromeDriverManager

# ---------------- CONFIG (via env)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PHONE = os.getenv("PHONE", "")
PASSWORD = os.getenv("PASSWORD", "")
URL = os.getenv("URL", "https://ebet.co.mz/games/go/spribe?id=aviator")
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")
PORT = int(os.getenv("PORT", os.getenv("SERVER_PORT", "8080")))
SCREENSHOT_DIR = os.getenv("SCREENSHOT_DIR", "/tmp")
Path(SCREENSHOT_DIR).mkdir(parents=True, exist_ok=True)

# backoff defaults (podem ser ajustados via env se quiser)
BASE_BACKOFF = int(os.getenv("BASE_BACKOFF", "8"))
MAX_BACKOFF = int(os.getenv("MAX_BACKOFF", "600"))

app = Flask(__name__)

historico = []
_last_telegram = 0

def send_telegram_text(msg, throttle_seconds=6):
    global _last_telegram
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[telegram] token/chat not set - pulando envio")
        return
    now = time.time()
    if now - _last_telegram < throttle_seconds:
        print("[telegram] throttle - pulando envio")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=15,
        )
        _last_telegram = now
    except Exception as e:
        print("Falha ao enviar Telegram:", e)

def send_telegram_photo(path, caption="", throttle_seconds=30):
    global _last_telegram
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[telegram] token/chat not set - pulando envio foto")
        return
    now = time.time()
    if now - _last_telegram < throttle_seconds:
        print("[telegram] photo throttle - pulando")
        return
    try:
        with open(path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                files={"photo": f},
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                timeout=30,
            )
        _last_telegram = now
    except Exception as e:
        print("Falha ao enviar foto Telegram:", e)

def screenshot_and_send(driver, label, path=None):
    if path is None:
        path = os.path.join(SCREENSHOT_DIR, f"shot_{int(time.time())}.png")
    try:
        driver.save_screenshot(path)
        print("[screenshot] salvo em", path)
        send_telegram_photo(path, caption=label)
    except Exception as e:
        print("Erro screenshot/send:", e)

def safe_find_elements(driver, selector, max_retries=4, sleep_between=0.3):
    for attempt in range(max_retries):
        try:
            elems = driver.find_elements(By.CSS_SELECTOR, selector)
            return elems
        except StaleElementReferenceException:
            time.sleep(sleep_between)
            continue
        except Exception as e:
            print("safe_find_elements erro:", e)
            time.sleep(sleep_between)
    return []

def click_aviator_if_found(driver):
    imgs = safe_find_elements(driver, "img.landing-page__item-image")
    for img in imgs:
        try:
            src = (img.get_attribute("src") or "").lower()
            alt = (img.get_attribute("alt") or "").lower()
            if "aviator" in src or "aviator" in alt:
                driver.execute_script("arguments[0].click();", img)
                print("Clique Aviator executado")
                return True
        except StaleElementReferenceException:
            continue
        except Exception as e:
            print("Erro ao clicar aviator:", e)
    return False

def coletar_historico_dom(driver):
    items = safe_find_elements(driver, "div.payouts-block div.payout")
    vals = []
    for el in items:
        try:
            txt = el.text.strip()
            m = re.search(r"(\d+(\.\d+)?)", txt)
            if m:
                vals.append(float(m.group(1)))
        except Exception:
            continue
    return vals

def page_shows_rate_limit(driver):
    try:
        body = driver.page_source.lower()
    except Exception:
        return False
    checks = ["rate limit", "too many requests", "429", "rate-limited", "rate_limited", "try again later"]
    for token in checks:
        if token in body:
            return True
    return False

def _detect_chrome_binary():
    # procura binários comuns
    candidates = ["/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

def iniciar_scraper():
    global historico
    base_backoff = BASE_BACKOFF
    max_backoff = MAX_BACKOFF
    backoff = base_backoff

    while True:
        driver = None
        try:
            print("=== iniciar_scraper: iniciando navegador ===")
            send_telegram_text("🟢 Iniciando Aviator (modo container)...")

            chrome_options = Options()
            if HEADLESS:
                chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1366,768")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-popup-blocking")
            chrome_options.add_argument("--disable-infobars")
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--remote-debugging-port=9222")
            chrome_options.add_argument("--disable-dev-tools")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
            )

            chrome_bin = _detect_chrome_binary()
            if chrome_bin:
                print("Usando binario chromium:", chrome_bin)
                chrome_options.binary_location = chrome_bin

            # service chromedriver (preferir /usr/bin/chromedriver se existir)
            service = None
            if os.path.exists("/usr/bin/chromedriver"):
                print("Usando /usr/bin/chromedriver")
                service = Service("/usr/bin/chromedriver")
            else:
                # fallback: webdriver-manager download (mais lento na 1a vez)
                print("Baixando chromedriver via webdriver-manager (fallback)")
                chromedriver_path = ChromeDriverManager().install()
                service = Service(chromedriver_path)

            driver = webdriver.Chrome(service=service, options=chrome_options)
            wait = WebDriverWait(driver, 30)

            print("Abrindo URL:", URL)
            driver.get(URL)
            time.sleep(6)
            # enviar screenshot inicial somente se token setado (opcional)
            try:
                screenshot_and_send(driver, "Página inicial aberta")
            except Exception:
                pass

            # clique aviator landing
            click_aviator_if_found(driver)
            time.sleep(2)

            # preencher login se existir (tenta IDs comuns; adapta conforme site)
            try:
                # esses IDs podem variar — aqui é versão direta do teu exemplo; para container, prefer env
                phone = None
                password = None
                try:
                    phone = driver.find_element(By.ID, "phone-input")
                    password = driver.find_element(By.ID, "password-input")
                except Exception:
                    # fallback: procurar inputs por tipo/name
                    try:
                        phone = driver.find_element(By.CSS_SELECTOR, "input[type='tel'], input[name='phone']")
                    except Exception:
                        phone = None
                    try:
                        password = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
                    except Exception:
                        password = None

                if phone and password and PHONE and PASSWORD:
                    try:
                        # rodar typing humano leve para telefone (mas não obrigatório)
                        try:
                            phone.clear()
                            for ch in PHONE:
                                phone.send_keys(ch)
                                time.sleep(random.uniform(0.08, 0.22))
                        except Exception:
                            try:
                                driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", phone, PHONE)
                            except Exception:
                                pass
                        # setar password via js (mais confiável em muitos sites)
                        try:
                            driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", password, PASSWORD)
                        except Exception:
                            try:
                                password.clear()
                                password.send_keys(PASSWORD)
                            except Exception:
                                pass

                        # clicar botão de submit se houver
                        try:
                            btn = driver.find_element(By.CSS_SELECTOR, "input.btn-session, button[type='submit'], button[class*='login']")
                            driver.execute_script("arguments[0].click();", btn)
                            print("Login enviado")
                            try:
                                screenshot_and_send(driver, "Login enviado")
                            except Exception:
                                pass
                        except Exception:
                            print("Botão de login não encontrado (fallback).")
                    except StaleElementReferenceException:
                        print("Stale ao preencher login, tentando adiar")
                        time.sleep(2)
                else:
                    print("Campos de login não encontrados no contexto atual (já logado ou layout diferente).")
            except Exception as e:
                print("Erro no bloco de login:", e)

            time.sleep(6)
            click_aviator_if_found(driver)
            time.sleep(4)

            # se abriu nova aba, trocar para ela
            handles = driver.window_handles
            if len(handles) > 1:
                driver.switch_to.window(handles[-1])
                print("Trocou para nova aba do jogo")

            # localizar primeiro iframe que contenha 'spribe' no src
            iframe1 = None
            for f in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    src = (f.get_attribute("src") or "").lower()
                    if "spribe" in src and "launch" not in src:
                        iframe1 = f
                        break
                except Exception:
                    continue

            if iframe1:
                driver.switch_to.frame(iframe1)
                print("Entrou no iframe externo")
                time.sleep(2)
            else:
                print("iframe externo não encontrado (continuando, pode estar tudo em root)")

            # tentar achar iframe interno launch.spribegaming
            iframe2 = None
            for f in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    src = (f.get_attribute("src") or "").lower()
                    if "spribegaming" in src or "launch.spribegaming" in src or "launch.spribe" in src:
                        iframe2 = f
                        break
                except Exception:
                    continue

            if iframe2:
                driver.switch_to.frame(iframe2)
                print("Entrou no iframe interno Spribe")
                time.sleep(3)
            else:
                print("iframe interno (launch) não encontrado - pode carregar depois")

            # Agora: não recarregamos a Spribe. Vamos monitorar o DOM com polling lento.
            print("Aguardando payouts aparecerem (monitorando sem forçar reloads)...")
            total_wait_start = time.time()
            payouts = []
            while True:
                # Detecta sinais de rate-limit direto no HTML/iframe
                if page_shows_rate_limit(driver):
                    # backoff exponencial com jitter
                    jitter = random.uniform(0.2, 1.2)
                    sleep_time = min(max_backoff, backoff) + jitter
                    send_telegram_text(f"⚠️ Rate limit detectado. Dormindo {int(sleep_time)}s antes de tentar de novo.")
                    print(f"Rate limit detectado → dormindo {sleep_time}s")
                    time.sleep(sleep_time)
                    backoff = min(max_backoff, backoff * 2)
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass
                # tentar coletar payouts
                try:
                    payouts = driver.find_elements(By.CSS_SELECTOR, "div.payouts-block div.payout")
                    if payouts and len(payouts) > 0:
                        print("Payouts encontrados:", len(payouts))
                        break
                except StaleElementReferenceException:
                    print("StaleElementReference ao buscar payouts - re-tentando")
                    time.sleep(1)
                except WebDriverException as e:
                    print("WebDriverException ao buscar payouts:", e)
                    sleep_time = min(max_backoff, backoff) + random.uniform(0.5, 1.5)
                    send_telegram_text(f"⚠️ WebDriverException ao buscar payouts. Dormindo {int(sleep_time)}s")
                    time.sleep(sleep_time)
                    backoff = min(max_backoff, backoff * 2)
                if time.time() - total_wait_start > 90:
                    send_telegram_text("⚠️ Ainda sem payouts depois de 90s — aumentando backoff e aguardando.")
                    time.sleep(min(max_backoff, backoff))
                    backoff = min(max_backoff, backoff * 2)
                    total_wait_start = time.time()
                time.sleep(2)

            # reset de backoff quando encontramos payouts
            backoff = base_backoff
            send_telegram_text("🚀 Aviator conectado (payouts detectados).")
            try:
                screenshot_and_send(driver, "Dentro do jogo (payouts detectados)")
            except Exception:
                pass

            # coleta inicial do histórico
            historico = coletar_historico_dom(driver)
            print("Historico inicial:", historico[:8])

            # monitoring loop (não recarrega iframe/URL - apenas consulta DOM)
            while True:
                try:
                    novos = coletar_historico_dom(driver)
                    if novos and novos != historico:
                        historico = novos
                        print("Novo histórico detectado (len):", len(historico))
                        lista = ", ".join(f"{v:.2f}x" for v in historico[:20])
                        send_telegram_text(f"📊 AVIATOR\n\n[{lista}]\n\nÚltimo: *{historico[0]:.2f}x*", throttle_seconds=10)
                        if random.random() < 0.6:
                            screenshot_and_send(driver, "Histórico atualizado")
                    time.sleep(5 + random.uniform(0, 2))
                except StaleElementReferenceException:
                    print("StaleElementReference no loop de monitoramento — re-tentando rápido")
                    time.sleep(1)
                except WebDriverException as e:
                    print("WebDriverException no monitor loop:", e)
                    send_telegram_text(f"⚠️ WebDriverException no monitor loop: {e}")
                    break

        except Exception as e:
            print("Erro geral no scraper:", type(e).__name__, e)
            traceback.print_exc()
            try:
                send_telegram_text(f"🔥 ERRO SCRAPER: {type(e).__name__} - {e}")
            except Exception:
                pass
            sleep_time = min(MAX_BACKOFF, backoff + random.uniform(1, 3))
            print(f"Dormindo {int(sleep_time)}s antes de reiniciar scraper...")
            time.sleep(sleep_time)
            backoff = min(MAX_BACKOFF, backoff * 2)
        finally:
            try:
                if driver:
                    print("Fechando driver...")
                    driver.quit()
            except Exception:
                pass
            time.sleep(3)


# Flask API
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
    return "AVIATOR BOT (container mode)"


if __name__ == "__main__":
    t = threading.Thread(target=iniciar_scraper, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=PORT)
