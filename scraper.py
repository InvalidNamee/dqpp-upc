"""Selenium 页面交互与解析 —— 登录检查、获取课程列表、答题流程、提取答案，不直接操作数据库。"""

import logging
import random
import re
from typing import Optional

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from config import get_config
from utils import (
    safe_find_element,
    short_sleep,
    wait_for_clickable,
    wait_for_element_present,
)

logger = logging.getLogger(__name__)

# ---- 课程相关 ----


def check_login(wait_element: WebElement) -> bool:
    """根据传入的元素判断登录状态，若 w1150 div 存在即视为已登录。"""
    return wait_element is not None


def ensure_login(driver: WebDriver) -> None:
    """自动完成统一身份认证登录，无需人工交互。

    流程：
    1. 访问首页 → 自动跳转到 /login/#/guide
    2. 点击"统一身份认证登录" → 跳转到 CAS
    3. 在 CAS iframe 中通过 JS 注入凭据并提交（绕过 Vue DOM 不稳定问题）
    4. 验证登录成功（跳转回 rdjy 并出现课程列表容器）
    """
    cfg = get_config()
    logger.info("开始自动登录...")

    # Step 1: 访问首页
    driver.get(cfg.base_url)
    short_sleep(2)
    logger.info("当前页面 URL: %s", driver.current_url)

    # Step 2: 点击"统一身份认证登录"按钮
    try:
        unified_btn = wait_for_clickable(
            driver, By.XPATH, "//button[contains(text(),'统一身份认证登录')]", timeout=10
        )
        unified_btn.click()
        logger.info("已点击'统一身份认证登录'")
    except TimeoutException:
        logger.info("未找到'统一身份认证登录'按钮，尝试直接检测登录状态")
        _verify_logged_in(driver)
        return

    # Step 3: 等待 CAS 页面 + iframe 加载
    short_sleep(3)
    logger.info("CAS 页面 URL: %s", driver.current_url)

    try:
        wait_for_element_present(driver, By.CSS_SELECTOR, "iframe[src*='login-normal']", timeout=10)
        driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR, "iframe[src*='login-normal']"))
        short_sleep(2)

        # 用 JS 直接操作 Vue 组件数据并触发登录，避免 DOM 交互的 element-not-found 问题
        js_code = f"""
        var app = document.querySelector('#app').__vue__;
        app.username = {_js_str(cfg.username)};
        app.password = {_js_str(cfg.password)};
        app.passwordLogin();
        """
        driver.execute_script(js_code)
        logger.info("已通过 JS 注入凭据并触发登录，等待跳转...")

        driver.switch_to.default_content()
    except (TimeoutException, NoSuchElementException) as e:
        logger.error("CAS 登录表单操作失败: %s", e)
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        raise

    # Step 4: 等待 CAS 跳转回 rdjy，然后主动 GET 课程列表页
    short_sleep(5)
    _verify_logged_in(driver)


def _js_str(s: str) -> str:
    """将 Python 字符串安全地转为 JavaScript 字符串字面量（单引号）。"""
    import json
    return json.dumps(s, ensure_ascii=False)


def _verify_logged_in(driver: WebDriver) -> None:
    """验证登录状态 —— GET 课程列表页，检查 ul.lesson_c_ul 是否存在。"""
    cfg = get_config()
    for attempt in range(2):
        driver.get(f"{cfg.base_url}/jjfz/lesson")
        try:
            wait_for_element_present(driver, By.CSS_SELECTOR, "ul.lesson_c_ul", timeout=8)
            logger.info("登录状态验证通过，已进入课程列表页")
            return
        except TimeoutException:
            logger.warning("登录验证第 %d 次失败，3 秒后重试...", attempt + 1)
            short_sleep(3)
    raise RuntimeError("登录失败：2 次尝试后仍未检测到登录状态，请检查用户名密码或是否有验证码")


def get_lesson_list(driver: WebDriver) -> list[dict]:
    """登录后从课程列表页获取所有课程信息（lesson_id / title / course_name / max_score / attempt_count）。"""
    cfg = get_config()
    driver.get(f"{cfg.base_url}/jjfz/lesson")

    try:
        ul = wait_for_element_present(driver, By.CSS_SELECTOR, "ul.lesson_c_ul", timeout=8)
    except TimeoutException:
        logger.warning("等待课程列表超时，刷新重试...")
        driver.refresh()
        try:
            ul = wait_for_element_present(driver, By.CSS_SELECTOR, "ul.lesson_c_ul", timeout=8)
        except TimeoutException:
            logger.warning("仍未找到课程列表")
            return []

    items = ul.find_elements(By.TAG_NAME, "li")
    lessons: list[dict] = []
    for li in items:
        info = _parse_lesson_item(li)
        if info:
            lessons.append(info)
    logger.info("获取到 %d 门课程", len(lessons))
    return lessons


def _parse_lesson_item(li: WebElement) -> Optional[dict]:
    """从单个课程 `<li>` 中解析 lesson_id、标题、成绩、次数等。"""
    try:
        self_link = li.find_element(By.CSS_SELECTOR, "a.self_text")
        href = self_link.get_attribute("href") or ""
        lesson_id = extract_lesson_id_from_url(href)
        if not lesson_id:
            return None

        title_el = safe_find_element(li, By.CSS_SELECTOR, ".lesson_center_dl dt")
        title = title_el.text.strip() if title_el else ""

        course_el = safe_find_element(li, By.CSS_SELECTOR, ".lesson_center_dl dd")
        course_text = course_el.text.strip() if course_el else ""

        attempt_count = 0
        max_score = 0
        parent_text = li.text or ""
        m_attempt = re.search(r"测试次数[：:]\s*(\d+)", parent_text)
        if m_attempt:
            attempt_count = int(m_attempt.group(1))
        m_score = re.search(r"最高成绩[：:]\s*(\d+)", parent_text)
        if m_score:
            max_score = int(m_score.group(1))

        return {
            "lesson_id": lesson_id,
            "title": title,
            "course_name": course_text,
            "max_score": max_score,
            "attempt_count": attempt_count,
        }
    except NoSuchElementException:
        return None


def extract_lesson_id_from_url(url: str) -> Optional[int]:
    """从 URL 中提取 lesson_id 参数值。"""
    m = re.search(r"lesson_id=(\d+)", url)
    return int(m.group(1)) if m else None


# ---- 答题流程 ----


def click_start_exam(driver: WebDriver, lesson_id: int) -> bool:
    """通过 lesson_id 在课程列表页定位并点击 '开始自测' 链接，进入答题页面。

    每次都从当前页面重新定位元素，避免 StaleElementReferenceException。
    """
    cfg = get_config()
    try:
        driver.get(f"{cfg.base_url}/jjfz/lesson")
        try:
            ul = wait_for_element_present(driver, By.CSS_SELECTOR, "ul.lesson_c_ul", timeout=8)
        except TimeoutException:
            driver.refresh()
            ul = wait_for_element_present(driver, By.CSS_SELECTOR, "ul.lesson_c_ul", timeout=8)

        link = ul.find_element(By.CSS_SELECTOR, f"a.self_text[href*='lesson_id={lesson_id}']")
        link.click()
        wait_for_element_present(driver, By.CSS_SELECTOR, ".cont_right_num", timeout=10)
        logger.info("成功进入答题页面: lesson_id=%d", lesson_id)
        return True
    except (NoSuchElementException, TimeoutException) as e:
        logger.error("进入答题页面失败 lesson_id=%d: %s", lesson_id, e)
        return False


def get_question_card_ids(driver: WebDriver) -> list[str]:
    """获取答题卡中所有题目的 ID 列表——遍历全部 ul.exam_ul 分组。"""
    wait_for_element_present(driver, By.CSS_SELECTOR, "ul.exam_ul", timeout=10)
    ids: list[str] = []
    for ul in driver.find_elements(By.CSS_SELECTOR, "ul.exam_ul"):
        for li in ul.find_elements(By.TAG_NAME, "li"):
            qid = li.get_attribute("id") or ""
            if qid:
                ids.append(qid)
    logger.info("答题卡共 %d 道题 (%d 组)", len(ids), len(driver.find_elements(By.CSS_SELECTOR, "ul.exam_ul")))
    return ids


def detect_question_type(driver: WebDriver) -> str:
    """根据当前题目区域标题推断题型（'single' / 'multi' / 'judge'）。

    题型信息在 .e_cont_title 中（如"单选题 （每题5分）..."），
    不在 .exam_list 内（.exam_list 只有题干+选项）。
    """
    try:
        title_el = driver.find_element(By.CSS_SELECTOR, ".e_cont_title")
        text = title_el.text.strip()
    except NoSuchElementException:
        text = ""
    if "多选" in text:
        return "multi"
    if "判断" in text:
        return "judge"
    return "single"


def get_question_text(driver: WebDriver) -> str:
    """获取当前题目题干文本（不含题型标记）。"""
    try:
        exam_h2 = driver.find_element(By.CSS_SELECTOR, ".exam_h2")
        return exam_h2.text.strip()
    except NoSuchElementException:
        return ""


def get_option_elements(driver: WebDriver, qtype: str) -> list[WebElement]:
    """获取当前题目的选项 input 元素列表。

    单选/判断使用 radio，多选使用 checkbox。
    """
    if qtype == "multi":
        return driver.find_elements(By.CSS_SELECTOR, ".exam_list input[type='checkbox']")
    return driver.find_elements(By.CSS_SELECTOR, ".exam_list input[type='radio']")


def _click_option_element(opt: WebElement) -> None:
    """点击选项 —— 点击包裹 input 的父级 <label>。"""
    try:
        label = opt.find_element(By.XPATH, "./parent::label")
        label.click()
    except NoSuchElementException:
        opt.click()


def answer_question(
    driver: WebDriver,
    qtype: str,
    known_answers: Optional[list] = None,
) -> list:
    """对当前题目进行作答。已知答案则勾选匹配项，否则随机作答。

    点击选项时优先点击关联的 <label> 或父级 <li>，以避免隐藏 <input> 的
    element-not-interactable 问题。

    Args:
        driver: WebDriver 实例。
        qtype: 题型（'single'/'multi'/'judge'）。
        known_answers: 已知的正确答案 value 列表（单选/判断为单元素列表）。

    Returns:
        实际选中的 value 列表。
    """
    options = get_option_elements(driver, qtype)
    if not options:
        logger.warning("未找到任何选项")
        return []

    selected_values: list = []

    if known_answers:
        known_set = set(str(v) for v in known_answers)
        for opt in options:
            val = opt.get_attribute("value") or ""
            if val in known_set:
                _click_option_element(opt)
                selected_values.append(val)
        logger.info("使用已知答案作答: %s", selected_values)
    else:
        if qtype == "multi":
            count = random.randint(1, len(options))
            chosen = random.sample(options, count)
            for opt in chosen:
                _click_option_element(opt)
                selected_values.append(opt.get_attribute("value") or "")
        else:
            chosen = random.choice(options)
            _click_option_element(chosen)
            selected_values.append(chosen.get_attribute("value") or "")
        logger.info("随机作答: %s", selected_values)

    return selected_values


def click_question_card(driver: WebDriver, card_id: str, index: int) -> bool:
    """通过 ID 重新定位答题卡题目并点击，避免 stale element 问题。

    优先原生 click，被 label 拦截时用 JS 派发鼠标事件序列。
    """
    try:
        card = driver.find_element(By.ID, card_id)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
        short_sleep(0.1)
        try:
            card.click()
        except ElementClickInterceptedException:
            driver.execute_script("""
                var el = arguments[0];
                ['mousedown','mouseup','click'].forEach(function(t){
                    el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true}));
                });
            """, card)
        short_sleep(0.6)
        return True
    except NoSuchElementException:
        logger.error("第 %d 题卡片 ID=%s 未找到", index + 1, card_id)
        return False
    except Exception as e:
        logger.error("点击第 %d 题失败: %s", index + 1, e)
        return False


def check_card_answered(driver: WebDriver, card_id: str) -> bool:
    """检查题目是否已作答——按 ID 重新定位卡片并检查 class 或选项勾选状态。"""
    try:
        card = driver.find_element(By.ID, card_id)
        cls = card.get_attribute("class") or ""
        if "done" in cls or "exam_full" in cls:
            return True
    except NoSuchElementException:
        pass
    try:
        for opt in driver.find_elements(By.CSS_SELECTOR, ".answer_list input"):
            if opt.is_selected():
                return True
    except NoSuchElementException:
        pass
    return False


# ---- 提交 ----


def submit_exam(driver: WebDriver) -> bool:
    """点击交卷按钮，等待确认弹窗，根据配置决定自动提交或等待确认。"""
    cfg = get_config()
    try:
        submit_btn = wait_for_clickable(driver, By.ID, "submit_exam", timeout=10)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", submit_btn)
        short_sleep(0.2)
        submit_btn.click()
        logger.info("已点击交卷按钮")

        wait_for_element_present(driver, By.CSS_SELECTOR, ".public_cont", timeout=10)

        if cfg.auto_submit:
            confirm_btn = wait_for_clickable(driver, By.CSS_SELECTOR, ".public_submit", timeout=10)
            confirm_btn.click()
            logger.info("自动确认提交")
        else:
            logger.warning("DQPP_AUTO_SUBMIT=false，跳过自动提交（调试模式）")
            return False

        short_sleep(2)
        return True
    except (NoSuchElementException, TimeoutException) as e:
        logger.error("提交试卷失败: %s", e)
        return False


# ---- 答案收集 ----


def click_view_detail(driver: WebDriver) -> bool:
    """点击 '查看考试详情' 按钮，进入详情页面。"""
    try:
        # 提交后可能停留在结果页，也有可能直接跳转
        short_sleep(2)
        btn = wait_for_clickable(driver, By.CSS_SELECTOR, ".submit_btn2", timeout=15)
        driver.execute_script("arguments[0].click();", btn)
        wait_for_element_present(driver, By.CSS_SELECTOR, ".error_box_lists", timeout=15)
        logger.info("已进入考试详情页面")
        return True
    except (NoSuchElementException, TimeoutException) as e:
        # 如果 .submit_btn2 没有出现，可能提交后直接进入了详情页或返回了列表
        try:
            wait_for_element_present(driver, By.CSS_SELECTOR, ".error_box_lists", timeout=5)
            logger.info("已在考试详情页面（无需点击按钮）")
            return True
        except TimeoutException:
            logger.error("进入考试详情页面失败: %s", e)
            return False


def collect_answers_from_detail(
    driver: WebDriver,
    question_order_map: list[dict],
    lesson_id: int,
) -> list[dict]:
    """从考试详情页面收集正确答案，并与答题时的题号顺序做实体对齐。

    Args:
        driver: WebDriver 实例。
        question_order_map: 答题时记录的列表，每个元素为 {"index": 0-based, "question_id": xxx}。
        lesson_id: 课程 ID。

    Returns:
        list[dict]: 收集到的答案列表，每个元素包含 question_id, lesson_id, type, question_text, answer_values。
    """
    results: list[dict] = []
    try:
        error_subs = driver.find_elements(By.CSS_SELECTOR, ".error_sub")
    except NoSuchElementException:
        logger.warning("考试详情页未找到 .error_sub 区块")
        return results

    if not error_subs:
        logger.warning("考试详情页无题目（可能是满分）")
        return results

    for i, block in enumerate(error_subs):
        if i >= len(question_order_map):
            logger.warning("详情页题目数(%d)超过答题卡题目数(%d)，跳过多余项", len(error_subs), len(question_order_map))
            break

        question_id = question_order_map[i]["question_id"]
        qtype, question_text, correct_values = _parse_detail_block(block)

        if correct_values:
            results.append({
                "question_id": question_id,
                "lesson_id": lesson_id,
                "type": qtype,
                "question_text": question_text,
                "answer_values": correct_values,
            })
            logger.info("收集到答案: question_id=%d, type=%s, answers=%s", question_id, qtype, correct_values)
        else:
            logger.warning("未提取到正确答案: question_id=%d", question_id)

    return results


def _parse_detail_block(block: WebElement) -> tuple[str, str, list]:
    """解析单个 .error_sub 区块，提取题型、题干文本、正确答案。

    Returns:
        (type, question_text, answer_values)
    """
    qtype = "single"
    question_text = ""
    correct_values: list = []

    try:
        title_el = block.find_element(By.CSS_SELECTOR, ".sub_title h3")
        title_text = title_el.text.strip()
        if "多选" in title_text:
            qtype = "multi"
        elif "判断" in title_text:
            qtype = "judge"
    except NoSuchElementException:
        pass

    try:
        question_el = block.find_element(By.CSS_SELECTOR, ".sub_title .exam_h2")
        question_text = question_el.text.strip()
    except NoSuchElementException:
        pass

    if qtype == "multi":
        correct_values = _parse_multi_correct_answers(block)
    else:
        correct_values = _parse_single_correct_answers(block)

    return qtype, question_text, correct_values


def _parse_single_correct_answers(block: WebElement) -> list:
    """从单选/判断题详情中提取正确答案 value。正确答案的 `<li>` 带有 `class='result_cut'`。"""
    try:
        lis = block.find_elements(By.CSS_SELECTOR, ".exam_result2 li")
        for li in lis:
            cls = li.get_attribute("class") or ""
            if "result_cut" in cls:
                inp = safe_find_element(li, By.TAG_NAME, "input")
                if inp:
                    val = inp.get_attribute("value") or ""
                    if val:
                        return [val]
    except NoSuchElementException:
        pass
    return []


def _parse_multi_correct_answers(block: WebElement) -> list:
    """从多选题详情中提取正确答案 value。正确答案的 `<li>` 带有 `class='result_cut'`。"""
    values = []
    try:
        lis = block.find_elements(By.CSS_SELECTOR, ".exam_result_box2 li")
        for li in lis:
            cls = li.get_attribute("class") or ""
            if "result_cut" in cls:
                inp = safe_find_element(li, By.TAG_NAME, "input")
                if inp:
                    val = inp.get_attribute("value") or ""
                    if val:
                        values.append(val)
    except NoSuchElementException:
        pass
    return values
