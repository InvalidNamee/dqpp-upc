"""通用工具函数 —— 等待元素、解析数字等。"""

import re
import time
from typing import Optional

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


DEFAULT_TIMEOUT = 10


def wait_for_element(driver: WebDriver, by: str, value: str, timeout: int = DEFAULT_TIMEOUT) -> WebElement:
    """显式等待元素可见并返回。"""
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((by, value))
    )


def wait_for_element_present(driver: WebDriver, by: str, value: str, timeout: int = DEFAULT_TIMEOUT) -> WebElement:
    """显式等待元素存在于 DOM 中并返回。"""
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, value))
    )


def wait_for_clickable(driver: WebDriver, by: str, value: str, timeout: int = DEFAULT_TIMEOUT) -> WebElement:
    """显式等待元素可点击并返回。"""
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, value))
    )


def safe_find_element(parent, by: str, value: str) -> Optional[WebElement]:
    """从父元素中安全查找子元素，未找到返回 None。"""
    from selenium.common.exceptions import NoSuchElementException

    try:
        return parent.find_element(by, value)
    except NoSuchElementException:
        return None


def safe_find_elements(parent, by: str, value: str) -> list:
    """从父元素中安全查找子元素列表。"""
    from selenium.common.exceptions import NoSuchElementException

    try:
        return parent.find_elements(by, value)
    except NoSuchElementException:
        return []


def extract_number(text: str) -> int:
    """从文本中提取第一个数字，例如 '测试次数：3 次' -> 3，失败返回 0。"""
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else 0


def extract_question_index(text: str) -> int:
    """从 '1、【单选题】' 之类文本中提取题号。"""
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else 0


def short_sleep(seconds: float = 0.6) -> None:
    """短暂休眠，用于页面切换间隔，避免过快请求。"""
    time.sleep(seconds)
