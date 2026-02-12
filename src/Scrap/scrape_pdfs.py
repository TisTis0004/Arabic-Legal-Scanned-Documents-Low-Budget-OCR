import os
import time
import re
import requests

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException


DOWNLOAD_DIR = os.path.abspath("./data/raw")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]+', "_", name).strip()
    return name[:180]


def download_with_driver_cookies(driver, url: str, out_path: str):
    s = requests.Session()
    for c in driver.get_cookies():
        s.cookies.set(
            c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/")
        )

    headers = {"User-Agent": driver.execute_script("return navigator.userAgent;")}
    with s.get(url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(1024 * 256):
                if chunk:
                    f.write(chunk)


def find_next_li(driver):
    """
    Returns the <li> for "next page" or None if not found.
    Uses multiple selectors because the site markup can vary.
    """
    candidates = [
        (
            By.XPATH,
            "//li[.//span[contains(@class,'page-link') and @aria-label='Go to next page']]",
        ),
        (
            By.XPATH,
            "//li[.//*[contains(@class,'page-link') and @aria-label='Go to next page']]",
        ),
        # fallback 1: Arabic text exists somewhere in li
        (
            By.XPATH,
            "//li[contains(@class,'page-item') and .//*[contains(normalize-space(.),'التالي')]]",
        ),
        # fallback 2: last pagination item (often next)
        (By.CSS_SELECTOR, "ul.pagination li.page-item:last-child"),
    ]

    for by, sel in candidates:
        try:
            el = driver.find_element(by, sel)
            return el
        except NoSuchElementException:
            continue
    return None


driver = webdriver.Chrome()
wait = WebDriverWait(driver, 25)

try:
    driver.get("https://laws.moj.gov.sa/ar/legislations-regulations/?pageNumber=1")
    main_tab = driver.current_window_handle

    page = 1
    doc_counter = 1

    while True:
        print(f"\n📄 Page {page}")

        wait.until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "div.deatils.clickable")
            )
        )
        docs = driver.find_elements(By.CSS_SELECTOR, "div.deatils.clickable")
        print("Found documents:", len(docs))

        for i in range(len(docs)):
            docs = wait.until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "div.deatils.clickable")
                )
            )
            el = docs[i]

            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)

            try:
                ActionChains(driver).move_to_element(el).pause(0.1).click(el).perform()
            except Exception:
                driver.execute_script("arguments[0].click();", el)

            wait.until(lambda d: len(d.window_handles) > 1)
            pdf_tab = driver.window_handles[-1]
            driver.switch_to.window(pdf_tab)

            wait.until(lambda d: d.current_url and d.current_url != "about:blank")
            time.sleep(0.3)
            pdf_url = driver.current_url

            filename = safe_filename(f"document_{doc_counter:04}.pdf")
            out_path = os.path.join(DOWNLOAD_DIR, filename)

            print(f"⬇️  Downloading {filename}")
            download_with_driver_cookies(driver, pdf_url, out_path)

            driver.close()
            driver.switch_to.window(main_tab)

            doc_counter += 1
            time.sleep(0.2)

        # --- go to bottom so pagination definitely exists ---
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.4)

        # wait a bit for pagination to render
        try:
            wait.until(lambda d: find_next_li(d) is not None)
        except TimeoutException:
            print("❌ Couldn't find next button. Stopping.")
            break

        next_li = find_next_li(driver)
        if next_li is None:
            print("❌ Couldn't find next button. Stopping.")
            break

        if "disabled" in (next_li.get_attribute("class") or ""):
            print("\n✅ Last page reached. Done.")
            break

        # Click the inner control (span/a) reliably
        try:
            next_control = next_li.find_element(By.CSS_SELECTOR, ".page-link")
        except NoSuchElementException:
            next_control = next_li

        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", next_control
        )
        driver.execute_script("arguments[0].click();", next_control)

        # Wait for page to refresh: docs should go stale or count changes
        wait.until(EC.staleness_of(docs[0]))

        page += 1

finally:
    driver.quit()
