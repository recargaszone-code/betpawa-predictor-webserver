#!/usr/bin/env python3
# main.py — BETPAWA Aviator (fluxo humano 10s entre passos, screenshots por passo, /api/history)
import os
import time
import re
import random
import traceback
import threading
import requests
from pathlib import Path
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

# ---------------- CONFIG (hardcoded conforme solicitado - AMBIENTE DE TESTE) ----------------
TELEGRAM_TOKEN = "8742776802:AAHSzD1qTwCqMEOdoW9_pT2l5GfmMBWUZQY"
TELEGRAM_CHAT_ID = "7427648935"
PHONE = "857789345"
PIN = "2010"
URL = "https://www.betpawa.co.mz/games?gameId=aviator&filter=all&redirectBack=/games"
# -----------------------------------------------------------------------------------------

app = Flask(__name__)

# Estado compartilhado
global_history = []     # acumulador (até 50)
_history_lock = threading.Lock()

# pasta para screenshots locais (opcional)
SCREENSHOTS_DIR = Path("/tmp/aviator_screens")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

_last_telegram = 0
_TELEGRAM_MIN_INTERVAL = 3.0  # segundos (evita flood)


def send_telegram_text(msg, throttle_seconds=6):
    """Envia texto com throttle. throttle_seconds=0 => tenta enviar sempre."""
    global _last_telegram
    now = time.time()
    if throttle_seconds and (now - _last_telegram) < throttle_seconds:
        return False
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=12,
        )
        _last_telegram = now
        return True
    except Exception as e:
        print("Erro Telegram text:", e)
        return False


def send_telegram_photo(path, caption="", throttle_seconds=25):
    """Envia foto (arquivo local) para Telegram com throttle."""
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
    except Exception as e:
        print("Erro Telegram photo:", e)
        return False


def screenshot_save_and_send(driver, label):
    """Salva screenshot local e envia para Telegram (se possível)."""
    try:
        fname = f"{int(time.time())}_{abs(hash(label)) % 10000}.png"
        path = SCREENSHOTS_DIR / fname
        driver.save_screenshot(str(path))
        print(f"[screenshot] {label} -> {path}")
        # tentar enviar (throttle interno)
        send_telegram_photo(str(path), caption=label)
    except Exception as e:
        print("Falha screenshot_send:", e)


def safe_click(driver, el):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        el.click()
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", el)
            return True
        except Exception as e:
            print("safe_click falha:", e)
            return False


def js_set_value_and_dispatch(driver, element, value):
    try:
        driver.execute_script("""
            const el = arguments[0], val = arguments[1];
            try{ el.focus(); }catch(e){}
            try{ el.value = val; }catch(e){}
            try{ el.setAttribute('value', val); }catch(e){}
            try{ el.dispatchEvent(new Event('input', {bubbles:true})); }catch(e){}
            try{ el.dispatchEvent(new Event('change', {bubbles:true})); }catch(e){}
            try{ el.blur(); }catch(e){}
            return true;
        """, element, value)
        return True
    except Exception as e:
        print("js_set_value error:", e)
        return False


def coletar_historico_from_frame(driver):
    """Coleta valores .payout no contexto atual (deve estar dentro do iframe)."""
    out = []
    try:
        elems = driver.find_elements(By.CSS_SELECTOR, ".payouts-wrapper .payout, .payouts-block .payout, .payout")
        pat = re.compile(r"(\d+(\.\d+)?)")
        for e in elems:
            try:
                txt = e.text.strip()
                m = pat.search(txt)
                if m:
                    out.append(float(m.group(1)))
            except StaleElementReferenceException:
                continue
            except Exception:
                continue
    except Exception as e:
        # se cross-origin, a busca falhará — retornamos vazio
        print("coletar_historico_from_frame erro:", e)
    return out


def page_shows_rate_limit(driver):
    try:
        body = driver.page_source.lower()
        return any(token in body for token in ["rate limit", "too many requests", "429"])
    except Exception:
        return False


# ---------- driver start (stealth container) ----------
def start_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1366,768")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36")

    if os.path.exists("/usr/bin/chromium"):
        opts.binary_location = "/usr/bin/chromium"

    service = Service("/usr/bin/chromedriver") if os.path.exists("/usr/bin/chromedriver") else Service()

    driver = webdriver.Chrome(service=service, options=opts)

    # tenta injetar script para reduzir navigator.webdriver etc
    try:
        stealth = r"""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        try{ Object.defineProperty(navigator, 'languages', {get:()=>['pt-BR','pt']}); }catch(e){}
        try{ Object.defineProperty(navigator, 'plugins', {get:()=>[1,2,3]}); }catch(e){}
        """
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stealth})
    except Exception:
        pass

    time.sleep(0.4)
    return driver


# ---------- fluxo principal (cada passo espera ~10s) ----------
def iniciar_scraper():
    """
    Executa o fluxo passo-a-passo conforme solicitado:
    1) abrir URL
    2) clicar modal Login
    3) preencher telefone
    4) preencher PIN
    5) clicar Log In
    6) aguardar iframe do Aviator
    7) entrar no iframe e coletar histórico repetidamente (cada 10s)
    Em cada passo tira screenshot e envia para Telegram.
    """
    global global_history
    backoff = 8
    max_backoff = 600

    while True:
        driver = None
        try:
            send_telegram_text("🟢 Scraper iniciando (fluxo humano 10s por passo)", throttle_seconds=0)
            driver = start_driver()
            wait = WebDriverWait(driver, 30)

            # --- PASSO 1: abrir URL ---
            step = "PASSO 1: Abrindo URL"
            print(step)
            send_telegram_text(f"📍 {step}", throttle_seconds=0)
            driver.get(URL)
            # espera humana (≈10s)
            time.sleep(9 + random.uniform(0, 2))
            screenshot_save_and_send(driver, step)

            # --- PASSO 2: clicar botão Login (modal) ---
            step = "PASSO 2: Clicando botão Login (modal)"
            print(step)
            send_telegram_text(f"📍 {step}", throttle_seconds=0)
            try:
                login_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//button[@data-test-id='confirmation-modal-secondary-button' and (contains(.,'Login') or contains(.,'Log In'))]")),
                    # primeiro tenta localizar o botão exato
                )
                safe_click(driver, login_btn)
            except Exception as e:
                print("Login modal não encontrado (pode já estar visível):", e)
            time.sleep(9 + random.uniform(0, 2))
            screenshot_save_and_send(driver, step)

            # --- PASSO 3: preencher telefone ---
            step = "PASSO 3: Preenchendo telefone"
            print(step)
            send_telegram_text(f"📍 {step}", throttle_seconds=0)
            try:
                # seletor exato conforme você passou
                phone_elem = wait.until(EC.presence_of_element_located((By.ID, "phoneNumber")))
                # usar JS para garantir que o valor seja aplicado
                js_set_value_and_dispatch(driver, phone_elem, PHONE)
            except Exception as e:
                print("Falha ao localizar/preencher telefone:", e)
                send_telegram_text("⚠️ Falha ao localizar input telefone", throttle_seconds=0)
            time.sleep(9 + random.uniform(0, 2))
            screenshot_save_and_send(driver, step)

            # --- PASSO 4: preencher PIN ---
            step = "PASSO 4: Preenchendo PIN"
            print(step)
            send_telegram_text(f"📍 {step}", throttle_seconds=0)
            try:
                pin_elem = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "input[data-test-id='loginFormPasswordInput'], input[type='password']")))
                js_set_value_and_dispatch(driver, pin_elem, PIN)
            except Exception as e:
                print("Falha ao localizar/preencher PIN:", e)
                send_telegram_text("⚠️ Falha ao localizar input PIN", throttle_seconds=0)
            time.sleep(9 + random.uniform(0, 2))
            screenshot_save_and_send(driver, step)

            # --- PASSO 5: clicar Log In (submit) ---
            step = "PASSO 5: Clicando Log In (submit)"
            print(step)
            send_telegram_text(f"📍 {step}", throttle_seconds=0)
            try:
                submit = driver.find_element(By.CSS_SELECTOR, "button[data-test-id='logInButton'], button[type='submit']")
                # remover disabled caso esteja setado
                try:
                    if submit.get_attribute("disabled"):
                        driver.execute_script("arguments[0].removeAttribute('disabled');", submit)
                except Exception:
                    pass
                safe_click(driver, submit)
            except Exception as e:
                print("Falha ao clicar submit login:", e)
                send_telegram_text("⚠️ Falha ao clicar Botão Log In", throttle_seconds=0)
            time.sleep(9 + random.uniform(0, 2))
            screenshot_save_and_send(driver, step)

            # --- PASSO 6: aguardar iframe do jogo aparecer ---
            step = "PASSO 6: Aguardando iframe do Aviator"
            print(step)
            send_telegram_text(f"📍 {step}", throttle_seconds=0)
            iframe_el = None
            start = time.time()
            while time.time() - start < 45:
                try:
                    frames = driver.find_elements(By.TAG_NAME, "iframe")
                    for f in frames:
                        try:
                            src = (f.get_attribute("src") or "").lower()
                            title = (f.get_attribute("title") or "").lower()
                            if "launch.spribegaming.com" in src or "aviator-next.spribegaming.com" in src or "spribegaming" in src or "game-iframe" in title:
                                iframe_el = f
                                break
                        except Exception:
                            continue
                    if iframe_el:
                        break
                except Exception:
                    pass
                time.sleep(1.0 + random.uniform(0, 0.6))
            if not iframe_el:
                raise RuntimeError("iframe do Aviator não encontrado (timeout)")
            # trocar para iframe
            try:
                driver.switch_to.frame(iframe_el)
            except Exception as e:
                # se não puder trocar por cross-origin, tentar abrir src em nova aba
                try:
                    src = iframe_el.get_attribute("src")
                    if src:
                        driver.switch_to.default_content()
                        driver.execute_script("window.open(arguments[0]);", src)
                        driver.switch_to.window(driver.window_handles[-1])
                        time.sleep(3 + random.random()*1.5)
                    else:
                        raise
                except Exception as ex:
                    print("Falha ao acessar iframe (cross-origin):", ex)
                    raise RuntimeError("Falha ao abrir iframe / cross-origin")
            time.sleep(9 + random.uniform(0, 2))
            screenshot_save_and_send(driver, step)
            send_telegram_text("✅ Entrado no iframe do Aviator", throttle_seconds=0)

            # --- PASSO 7: captura inicial do histórico ---
            step = "PASSO 7: Capturando histórico inicial"
            print(step)
            send_telegram_text(f"📍 {step}", throttle_seconds=0)
            start = time.time()
            found = False
            while time.time() - start < 45:
                if page_shows_rate_limit(driver):
                    # se aparecer rate limit, dormir um pouco e tentar novamente
                    sleep_for = min(max(backoff, 8), 600) + random.uniform(0, 3)
                    send_telegram_text(f"⚠️ Rate limit detectado — dormindo {int(sleep_for)}s", throttle_seconds=0)
                    time.sleep(sleep_for)
                    backoff = min(600, (backoff * 2) if 'backoff' in locals() else 16)
                    continue
                vals = coletar_historico_from_frame(driver)
                if vals:
                    with _history_lock:
                        global_history = vals[:]  # inicia acumulador com o que estiver visível
                        # manter apenas 50
                        if len(global_history) > 50:
                            global_history = global_history[:50]
                    found = True
                    send_telegram_text(f"✅ Histórico inicial carregado ({len(global_history)} valores)", throttle_seconds=0)
                    break
                time.sleep(2 + random.uniform(0, 1))
            if not found:
                send_telegram_text("⚠️ Histórico inicial não detectado — seguirei no loop", throttle_seconds=0)

            # --- LOOP de polling do histórico: a cada ~10s ---
            print("Entrando no loop de polling (cada ~10s).")
            while True:
                try:
                    # coletar histórico atual
                    novos = coletar_historico_from_frame(driver)
                except WebDriverException as w:
                    print("WebDriverException durante coleta:", w)
                    raise

                if novos:
                    # comparar primeiro elemento para detectar mudança
                    with _history_lock:
                        prev0 = global_history[0] if global_history else None
                    if not prev0 or novos[0] != prev0:
                        # adicionar novos não duplicados no topo do acumulador
                        added = False
                        with _history_lock:
                            for v in novos:
                                if v not in global_history:
                                    global_history.insert(0, v)
                                    added = True
                            # truncar a 50
                            if len(global_history) > 50:
                                global_history = global_history[:50]
                            # criar uma cópia para log
                            snapshot = list(global_history)
                        if added:
                            # log e enviar snapshot parcial
                            lista = ", ".join(f"{x:.2f}x" for x in snapshot[:25])
                            print("[NOVO HIST] Últimos (top 25):", lista)
                            send_telegram_text(f"📊 NOVO HISTÓRICO (top {min(25,len(snapshot))}):\n[{lista}]\nÚltimo: *{snapshot[0]:.2f}x*", throttle_seconds=6)
                            # screenshot ocasional
                            if random.random() < 0.5:
                                screenshot_save_and_send(driver, "Histórico atualizado")
                else:
                    # sem elementos -> pode ser rate limit ou DOM diferente
                    if page_shows_rate_limit(driver):
                        send_telegram_text("⚠️ Rate limit detectado durante polling", throttle_seconds=0)
                        # aguardar um pouco mais
                        time.sleep(20 + random.uniform(0, 6))

                # cada passo: ~10s (human-like jitter)
                time.sleep(9 + random.uniform(0, 2))

        except Exception as e:
            print("Erro no scraper:", type(e).__name__, e)
            traceback.print_exc()
            send_telegram_text(f"🔥 ERRO SCRAPER: {type(e).__name__} - {e}", throttle_seconds=0)
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
            # esperar antes de tentar reiniciar (backoff simples)
            time.sleep(10 + random.uniform(0, 10))
            continue
        finally:
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
            # pequena pausa antes de novo ciclo
            time.sleep(3)


# -------- Flask endpoints (retornam JSON) ----------
@app.route("/api/history")
def api_history():
    with _history_lock:
        return jsonify(global_history)


@app.route("/api/last")
def api_last():
    with _history_lock:
        return jsonify(global_history[0] if global_history else None)


@app.route("/")
def home():
    return "BETPAWA AVIATOR - Histórico (fluxo humano 10s por passo)."

# -------- main ----------
if __name__ == "__main__":
    # start scraper thread
    t = threading.Thread(target=iniciar_scraper, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", "8080"))
    # run flask (development server) — em container é suficiente para testes
    app.run(host="0.0.0.0", port=port)
