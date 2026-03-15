import os
import re
import time
import random
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
)

from webdriver_manager.chrome import ChromeDriverManager


# ================= CONFIG =================

PHONE = "857789345"
PIN = "2010"

BASE_URL = "https://www.betpawa.co.mz/games"

POLL_SECONDS = 5

# ==========================================


def start_driver():

    opts = Options()

    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114 Safari/537.36"
    )

    service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=service, options=opts)

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    return driver


def coletar_historico(driver):

    numeros = []

    elems = driver.find_elements(By.CSS_SELECTOR, ".payout")

    regex = re.compile(r"(\d+(\.\d+)?)")

    for el in elems:

        try:

            txt = el.text.strip()

            m = regex.search(txt)

            if m:
                numeros.append(float(m.group(1)))

        except StaleElementReferenceException:
            continue

    return numeros


def main():

    driver = start_driver()

    wait = WebDriverWait(driver, 30)

    print("Abrindo Betpawa...")

    driver.get(BASE_URL)

    time.sleep(3)

    # ---------------- LOGIN ----------------

    print("Procurando botão Login...")

    try:

        login_btn = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(.,'Login')]")
            )
        )

        login_btn.click()

    except TimeoutException:
        print("Botão login não apareceu")

    time.sleep(2)

    print("Preenchendo telefone...")

    phone = wait.until(
        EC.presence_of_element_located((By.ID, "phoneNumber"))
    )

    phone.clear()
    phone.send_keys(PHONE)

    print("Preenchendo PIN...")

    pwd = wait.until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, "input[type='password']")
        )
    )

    pwd.clear()
    pwd.send_keys(PIN)

    submit = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(.,'Log In')]")
        )
    )

    submit.click()

    print("Login enviado")

    time.sleep(5)

    # ---------------- ABRIR AVIATOR ----------------

    print("Procurando Aviator...")

    aviator = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//img[contains(@src,'aviator')]")
        )
    )

    driver.execute_script("arguments[0].click()", aviator)

    time.sleep(6)

    # ---------------- ENTRAR NO IFRAME ----------------

    print("Procurando iframe...")

    iframe = wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//iframe[contains(@src,'spribe')]")
        )
    )

    driver.switch_to.frame(iframe)

    print("Dentro do jogo")

    historico = []

    # ---------------- LOOP ----------------

    while True:

        try:

            novos = coletar_historico(driver)

            if novos and novos != historico:

                historico = novos

                print(
                    "Histórico:",
                    ", ".join(f"{v:.2f}x" for v in historico[:20])
                )

                print("Último:", historico[0])

            time.sleep(POLL_SECONDS + random.uniform(1, 2))

        except StaleElementReferenceException:

            time.sleep(1)


if __name__ == "__main__":

    if not PHONE or not PIN:

        print("Defina as variáveis de ambiente:")

        print("BP_PHONE=seu_numero")
        print("BP_PIN=seu_pin")

    else:

        main()
