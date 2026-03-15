import time
import re

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ================= CREDENCIAIS TESTE =================

PHONE = "857789345"
PIN = "2010"

BASE_URL = "https://www.betpawa.co.mz/games"

# =====================================================


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


def coletar_historico(driver):

    valores = []

    elems = driver.find_elements(By.CSS_SELECTOR, ".payout")

    regex = re.compile(r"(\d+(\.\d+)?)")

    for el in elems:

        txt = el.text.strip()

        m = regex.search(txt)

        if m:
            valores.append(float(m.group(1)))

    return valores


def main():

    driver = start_driver()

    wait = WebDriverWait(driver, 30)

    print("Abrindo betpawa")

    driver.get(BASE_URL)

    time.sleep(5)

    # LOGIN

    print("Procurando botão login")

    login_btn = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(.,'Login')]")
        )
    )

    login_btn.click()

    time.sleep(2)

    phone = wait.until(
        EC.presence_of_element_located((By.ID, "phoneNumber"))
    )

    phone.send_keys(PHONE)

    pwd = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
    )

    pwd.send_keys(PIN)

    submit = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(.,'Log In')]")
        )
    )

    submit.click()

    print("Login enviado")

    time.sleep(6)

    # ABRIR AVIATOR

    print("Procurando Aviator")

    aviator = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//img[contains(@src,'aviator')]")
        )
    )

    driver.execute_script("arguments[0].click();", aviator)

    time.sleep(6)

    # IFRAME

    print("Procurando iframe")

    iframe = wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//iframe[contains(@src,'spribe')]")
        )
    )

    driver.switch_to.frame(iframe)

    historico = []

    print("Dentro do jogo")

    while True:

        novos = coletar_historico(driver)

        if novos and novos != historico:

            historico = novos

            print("Historico:", historico[:20])

        time.sleep(5)


if __name__ == "__main__":
    main()
