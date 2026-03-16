#!/usr/bin/env python3
# main.py - Betpawa Aviator (correção: WebDriverWait timeout e melhorias no login)
import os
import time
import re
import random
import threading
import traceback
from pathlib import Path
from flask import Flask, jsonify

import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, StaleElementReferenceException, WebDriverException
)

# ---------------- CONFIG (hardcoded - ambiente de teste) ----------------
TELEGRAM_TOKEN = "8742776802:AAHSzD1qTwCqMEOdoW9_pT2l5GfmMBWUZQY"
TELEGRAM_CHAT_ID = "7427648935"

PHONE = "857789345"
PIN = "2010"

URL = "https://www.betpawa.co.mz/games?gameId=aviator&filter=all&redirectBack=/games"
# -----------------------------------------------------------------------

app = Flask(__name__)

_history_lock = threading.Lock()
global_history = []

SCREEN_DIR = Path("/tmp/aviator_steps")
SCREEN_DIR.mkdir(parents=True, exist_ok=True)

_last_telegram = 0
DEFAULT_TG_THROTTLE = 3.0
DEFAULT_PHOTO_THROTTLE = 15.0


def send_telegram_text(msg: str, throttle_seconds: float = DEFAULT_TG_THROTTLE) -> bool:
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
        print("send_telegram_text failed:", e)
        return False


def send_telegram_photo(path: str, caption: str = "", throttle_seconds: float = DEFAULT_PHOTO_THROTTLE) -> bool:
    global _last_telegram
    now = time.time()
    if throttle_seconds and (now - _last_telegram) < throttle_seconds:
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
        print("send_telegram_photo failed:", e)
        return False


def save_and_send_screenshot(driver, label: str):
    try:
        fname = f"{int(time.time())}_{abs(hash(label)) % 10000}.png"
        path = SCREEN_DIR / fname
        driver.save_screenshot(str(path))
        print(f"[screenshot] {label} -> {path}")
        send_telegram_photo(str(path), caption=label)
    except Exception as e:
        print("save_and_send_screenshot error:", e)


def safe_click(driver, element) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        element.click()
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception as e:
            print("safe_click failed:", e)
            return False


def js_set_value_and_dispatch(driver, element, value: str) -> bool:
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
        print("coletar_historico_from_frame error:", e)
    return out


def page_shows_rate_limit(driver) -> bool:
    try:
        body = driver.page_source.lower()
        tokens = ["rate limit", "too many requests", "429", "rate-limited", "rate_limited"]
        return any(t in body for t in tokens)
    except Exception:
        return False


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
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114 Safari/537.36")

    if os.path.exists("/usr/bin/chromium"):
        opts.binary_location = "/usr/bin/chromium"

    service = Service("/usr/bin/chromedriver") if os.path.exists("/usr/bin/chromedriver") else Service()
    driver = webdriver.Chrome(service=service, options=opts)

    # injetar stealth script (tenta, ignora falhas)
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


def run_flow_human_like():
    """
    Fluxo passo-a-passo (≈10s each) com correções no uso de WebDriverWait.
    """
    global global_history
    base_backoff = 8
    backoff = base_backoff
    max_backoff = 600

    while True:
        driver = None
        try:
            send_telegram_text("🟢 Iniciando fluxo Betpawa Aviator (human-like)", throttle_seconds=0)
            driver = start_driver()
            wait = WebDriverWait(driver, 30)

            # PASSO 1 - abrir URL
            step = "PASSO 1: Abrindo URL"
            print(step)
            send_telegram_text(f"📍 {step}", throttle_seconds=0)
            driver.get(URL)
            time.sleep(9 + random.uniform(0, 2))
            save_and_send_screenshot(driver, step)

            # PASSO 2 - clicar modal 'Iniciar sessão'
            step = "PASSO 2: Clicando botão Iniciar sessão"
            print(step)
            send_telegram_text(f"📍 {step}", throttle_seconds=0)
            try:
                # esperar pelo botão modal (30s máximo)
                login_btn = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//button[@data-test-id='confirmation-modal-secondary-button' and (contains(.,'Iniciar sessão') or contains(.,'Login') or contains(.,'Log In'))]")
                    )
                )
                safe_click(driver, login_btn)
            except Exception as e:
                print("Login modal pode já estar visível ou não encontrado:", e)
            time.sleep(9 + random.uniform(0, 2))
            save_and_send_screenshot(driver, step)

            # PASSO 3 - preencher telefone
            step = "PASSO 3: Preenchendo telefone"
            print(step)
            send_telegram_text(f"📍 {step}", throttle_seconds=0)
            try:
                # CORREÇÃO: criar um WebDriverWait com timeout em vez de passar timeout ao until
                phone_elem = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.ID, "phoneNumber"))
                )
                # aplicar por JS (mais robusto)
                js_set_value_and_dispatch(driver, phone_elem, PHONE)
                # confirmar e refazer se necessário
                try:
                    cur = (phone_elem.get_attribute("value") or "").strip()
                    if not cur or PHONE not in cur:
                        js_set_value_and_dispatch(driver, phone_elem, PHONE)
                except Exception:
                    pass
            except Exception as e:
                print("Erro ao localizar/preencher telefone:", e)
                send_telegram_text("⚠️ Falha ao localizar input telefone", throttle_seconds=0)
            time.sleep(9 + random.uniform(0, 2))
            save_and_send_screenshot(driver, step)

            # PASSO 4 - preencher PIN
            step = "PASSO 4: Preenchendo PIN"
            print(step)
            send_telegram_text(f"📍 {step}", throttle_seconds=0)
            try:
                pin_elem = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "input[data-test-id='loginFormPasswordInput'], input[type='password']")
                    )
                )
                js_set_value_and_dispatch(driver, pin_elem, PIN)
                try:
                    curp = (pin_elem.get_attribute("value") or "").strip()
                    if not curp or PIN not in curp:
                        js_set_value_and_dispatch(driver, pin_elem, PIN)
                except Exception:
                    pass
            except Exception as e:
                print("Erro ao localizar/preencher PIN:", e)
                send_telegram_text("⚠️ Falha ao localizar input PIN", throttle_seconds=0)
            time.sleep(9 + random.uniform(0, 2))
            save_and_send_screenshot(driver, step)

            # PASSO 5 - clicar Log In (submit)
            step = "PASSO 5: Clicando Log In (submit)"
            print(step)
            send_telegram_text(f"📍 {step}", throttle_seconds=0)
            try:
                submit = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "button[data-test-id='logInButton'], button[type='submit']"))
                )
                # remover disabled se existir e for óbvio
                try:
                    if submit.get_attribute("disabled"):
                        driver.execute_script("arguments[0].removeAttribute('disabled');", submit)
                except Exception:
                    pass
                # usar safe_click; se falhar, usar JS click
                if not safe_click(driver, submit):
                    try:
                        driver.execute_script("arguments[0].click();", submit)
                    except Exception as e:
                        print("Falha ao clicar submit via JS:", e)
                        raise
            except Exception as e:
                print("Falha ao localizar/clicar submit:", e)
                send_telegram_text("⚠️ Falha ao clicar botão Log In", throttle_seconds=0)
            time.sleep(9 + random.uniform(0, 2))
            save_and_send_screenshot(driver, step)

            # PASSO 6 - aguardar iframe do Aviator
            step = "PASSO 6: Aguardando iframe do Aviator"
            print(step)
            send_telegram_text(f"📍 {step}", throttle_seconds=0)
            iframe_el = None
            start_t = time.time()
            while time.time() - start_t < 45:
                try:
                    frames = driver.find_elements(By.TAG_NAME, "iframe")
                    for f in frames:
                        try:
                            src = (f.get_attribute("src") or "").lower()
                            title = (f.get_attribute("title") or "").lower()
                            if ("launch.spribegaming" in src) or ("aviator-next.spribegaming" in src) or ("spribegaming" in src) or ("game-iframe" in title):
                                iframe_el = f
                                break
                        except Exception:
                            continue
                    if iframe_el:
                        break
                except Exception:
                    pass
                time.sleep(1.0 + random.random()*0.6)

            if not iframe_el:
                raise RuntimeError("iframe do Aviator não encontrado (timeout)")

            # tentar entrar no iframe; se cross-origin impedir, abrir src em nova aba
            try:
                driver.switch_to.frame(iframe_el)
            except Exception as e:
                print("switch_to.frame falhou (tentando abrir src em nova aba):", e)
                try:
                    src = iframe_el.get_attribute("src")
                    if src:
                        driver.switch_to.default_content()
                        driver.execute_script("window.open(arguments[0]);", src)
                        driver.switch_to.window(driver.window_handles[-1])
                        time.sleep(3 + random.random()*1.5)
                    else:
                        raise RuntimeError("iframe sem src")
                except Exception as ex:
                    print("Falha ao abrir iframe.src em nova aba:", ex)
                    raise RuntimeError("Não foi possível acessar iframe do jogo")

            time.sleep(9 + random.uniform(0, 2))
            save_and_send_screenshot(driver, step)
            send_telegram_text("✅ Entrado no contexto do jogo (iframe/aba)", throttle_seconds=0)

            # PASSO 7 - captura inicial do histórico e polling (~10s)
            step = "PASSO 7: Capturando histórico inicial"
            print(step)
            send_telegram_text(f"📍 {step}", throttle_seconds=0)
            start_t = time.time()
            found = False
            while time.time() - start_t < 45:
                if page_shows_rate_limit(driver):
                    sleep_for = min(max(backoff, 8), 600) + random.uniform(0, 3)
                    send_telegram_text(f"⚠️ Rate limit detectado — dormindo {int(sleep_for)}s", throttle_seconds=0)
                    time.sleep(sleep_for)
                    backoff = min(600, (backoff * 2) if backoff > 1 else 16)
                    continue
                vals = coletar_historico_from_frame(driver)
                if vals:
                    with _history_lock:
                        global_history = vals[:50]
                    found = True
                    send_telegram_text(f"✅ Histórico inicial detectado ({len(global_history)} valores)", throttle_seconds=0)
                    break
                time.sleep(2 + random.random()*1.0)
            if not found:
                send_telegram_text("⚠️ Histórico inicial não detectado — seguirei no polling", throttle_seconds=0)

            # polling loop (~10s)
            print("Iniciando polling (~10s) do histórico")
            while True:
                try:
                    novos = coletar_historico_from_frame(driver)
                except WebDriverException as w:
                    print("WebDriverException durante coleta:", w)
                    raise

                if novos:
                    with _history_lock:
                        prev0 = global_history[0] if global_history else None
                    if not prev0 or (novos and novos[0] != prev0):
                        added = False
                        with _history_lock:
                            for v in novos:
                                if v not in global_history:
                                    global_history.insert(0, v)
                                    added = True
                            if len(global_history) > 50:
                                global_history = global_history[:50]
                            snapshot = list(global_history)
                        if added:
                            lista = ", ".join(f"{x:.2f}x" for x in snapshot[:25])
                            print("[NOVO HIST] top25:", lista)
                            send_telegram_text(f"📊 NOVO HISTÓRICO (top{min(25,len(snapshot))}):\n[{lista}]\nÚltimo: *{snapshot[0]:.2f}x*", throttle_seconds=6)
                            if random.random() < 0.6:
                                save_and_send_screenshot(driver, "Histórico atualizado")
                else:
                    if page_shows_rate_limit(driver):
                        send_telegram_text("⚠️ Rate limit detectado durante polling", throttle_seconds=0)
                        time.sleep(20 + random.random()*5)

                time.sleep(9 + random.uniform(0, 2))

        except Exception as e:
            print("Erro no fluxo:", type(e).__name__, e)
            traceback.print_exc()
            send_telegram_text(f"🔥 ERRO SCRAPER: {type(e).__name__} - {e}", throttle_seconds=0)
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
            time.sleep(10 + random.random()*10)
            continue
        finally:
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
            time.sleep(3)


@app.route("/api/history")
def api_history():
    with _history_lock:
        return jsonify(global_history)


@app.route("/api/last")
def api_last():
    with _history_lock:
        return jsonify(global_history[0] if global_history else None)


@app.route("/")
def index():
    return "BETPAWA AVIATOR - fluxo humano ~10s por passo. Use /api/history e /api/last."


if __name__ == "__main__":
    t = threading.Thread(target=run_flow_human_like, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
