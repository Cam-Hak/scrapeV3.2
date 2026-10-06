import time
import logging

from dotenv import load_dotenv
import os
import global_info
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.firefox.options import Options

def selenium_config_tns() -> webdriver:
    options = Options()

    # 1. Stealth: Disable the "navigator.webdriver" flag
    # This is the #1 reason for infinite reloads
    options.set_preference("dom.webdriver.enabled", False)
    options.set_preference("useAutomationExtension", False)

    # 2. Stealth: Set a common Desktop User-Agent
    # Makes the server think you are a human on a Windows machine
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
    options.set_preference("general.useragent.override", user_agent)

    # 3. Performance: Block images to speed up scraping
    options.set_preference("permissions.default.image", 1)

    # Stop Firefox from checking/applying updates mid-run
    options.set_preference("app.update.disabledForTesting", True)
    options.set_preference("app.update.auto", False)
    options.set_preference("app.update.enabled", False)
    options.set_preference("app.update.service.enabled", False)
    options.set_preference("app.update.background.scheduling.enabled", False)

    # 4. Sizing: Force a standard screen resolution
    # Prevents "0x0" detection which triggers bot traps
    options.add_argument("--width=1920")
    options.add_argument("--height=1080")

    # 5. Headless Toggle — honor the -H flag (shared via global_info)
    if global_info.run_headless:
        options.add_argument("--headless")

    driver = webdriver.Firefox(options=options)

    # Set an implicit wait as a fallback
    driver.implicitly_wait(60)

    return driver

def load_tns(driver, article_list):
    tns_url = "https://targetednews.com/"
    driver.get(tns_url)

    wait = WebDriverWait(driver, 10)
    load_dotenv()
    login_trigger = wait.until(EC.element_to_be_clickable((By.ID, 'login_button')))
    login_trigger.click()
    username = os.getenv('TNS_USER')
    password = os.getenv('TNS_PASS')
    user_input = wait.until(EC.presence_of_element_located((By.NAME, 'puserid')))
    pass_field = driver.find_element(By.NAME, 'ppw')

    user_input.send_keys(username)
    pass_field.send_keys(password)
    # 1. Use By.CSS_SELECTOR to find the button
    # 2. Use .click() at the end to perform the action
    login_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='submit'][value='Login']")))
    login_button.click()

    WebDriverWait(driver, 10).until(EC.url_contains("https://coder.targetednews.com/admin_menu_new.php"))

    if "https://coder.targetednews.com/admin_menu_new.php" not in driver.current_url:
        logging.error("  TNS login failed")
        return  # driver cleanup handled by start_load's finally block

    logging.info("  TNS login successful")
    input_story(driver,article_list)

def _wait_for(wait, locator, label):
    """Wait for an element and log which one failed if it times out."""
    try:
        return wait.until(EC.presence_of_element_located(locator))
    except Exception as e:
        logging.error(f"  TNS element not found: {label} (locator={locator})")
        raise

def _wait_clickable(wait, locator, label):
    """Same as _wait_for but for clickable elements."""
    try:
        return wait.until(EC.element_to_be_clickable(locator))
    except Exception as e:
        logging.error(f"  TNS element not clickable: {label} (locator={locator})")
        raise

def input_story(driver, article_dict):
    (headline_send, body_send, prompt_send, filename_send,
     link_send, comment_send, box_send, date_send) = article_dict

    driver.get("https://coder.targetednews.com/story_add.php")
    logging.debug("  Submitting to TNS")
    logging.debug(f"  Box: {box_send}, Filename: {filename_send}")

    wait = WebDriverWait(driver, 10)

    try:
        byline = _wait_for(wait, (By.NAME, 'by_line'), "byline")
        filename = _wait_for(wait, (By.NAME, 'filename'), "filename")
        comments = _wait_for(wait, (By.NAME, 'comments'), "comments")
        headline = _wait_for(wait, (By.NAME, 'headline'), "headline")
        story_txt = _wait_for(wait, (By.NAME, 'story_txt'), "story_txt")
        original_text_box = _wait_for(wait, (By.NAME, 'orig_txt'), "orig_txt")
        source_box = _wait_for(wait, (By.NAME, 'source'), "source")

        radio_button = _wait_clickable(
            wait, (By.CSS_SELECTOR, "input[name='source'][value='98']"), "source radio (98)"
        )
        radio_button.click()

        byline.send_keys("Carter Struck")
        headline.send_keys(headline_send)
        filename.send_keys(filename_send)
        comments.send_keys(comment_send)
        story_txt.send_keys(body_send)
        original_text_box.send_keys(prompt_send)
        source_box.send_keys("98")
        if box_send == "D":
            save_button = _wait_clickable(
                wait, (By.CSS_SELECTOR, "input[name='submit'][value='Save']"), "Save button"
            )
            save_button.click()
        else:
            editor_button = _wait_clickable(
                wait, (By.CSS_SELECTOR, "input[value='Save to Editor Box (4)']"), "Save to Editor Box (4)"
            )
            editor_button.click()
        time.sleep(1)
        logging.info("  TNS Submitted")
    except Exception as e:
        logging.error(f"  TNS submission failed at URL: {driver.current_url}")
        logging.error(f"  Page title: {driver.title}")
        raise

def start_load(article_list):
    driver = selenium_config_tns()
    try:
        load_tns(driver, article_list)
    finally:
        driver.quit()
if __name__ == "__main__":
    start_load(["Headline Test", "Body body body doing stuff", "Tell ai to do this", "XXXXfilename", "httpe:hehe", "Ther was an issue", "D", "Today", "original"])