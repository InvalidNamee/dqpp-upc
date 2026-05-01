"""主工作流编排 —— 串联初始化、登录检测、课程遍历、答题循环、答案收集、清理等步骤。"""

import logging
import sys
from typing import Optional

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.chrome.service import Service

from config import get_config, setup_logging
from database import (
    get_connection,
    get_question,
    init_db,
    upsert_lesson,
    upsert_question,
)
from scraper import (
    answer_question,
    check_card_answered,
    click_question_card,
    click_start_exam,
    click_view_detail,
    collect_answers_from_detail,
    ensure_login,
    get_lesson_list,
    get_option_value_map,
    get_options_list,
    get_question_card_ids,
    get_question_text,
    submit_exam,
    wait_for_exam_content,
)
from utils import safe_find_element, short_sleep

logger = logging.getLogger(__name__)


def create_driver() -> webdriver.Chrome:
    cfg = get_config()
    options = webdriver.ChromeOptions()
    if cfg.headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    service = Service(executable_path=cfg.driver_path) if cfg.driver_path else Service()
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def process_one_lesson(driver: webdriver.Chrome, conn, lesson_id: int) -> None:
    """对单门课程执行一次完整的 答题 + 答案收集 流程。

    Args:
        driver: WebDriver 实例。
        conn: 数据库连接。
        lesson_id: 课程 ID。
    """
    # 4.2 进入答题（每次从课程列表页重新定位链接，避免 stale element）
    if not click_start_exam(driver, lesson_id):
        return

    short_sleep(1)

    # 4.3 逐题作答——只存 ID，每次按 ID 重新定位避免 stale element
    card_ids = get_question_card_ids(driver)
    if not card_ids:
        logger.warning("课程 %d 答题卡中无题目", lesson_id)
        return

    question_order_map: list[dict] = []

    for idx, card_info in enumerate(card_ids):
        card_id = card_info["id"]
        qtype = card_info["type"]

        if not click_question_card(driver, card_id, idx):
            continue

        wait_for_exam_content(driver)

        # 记录 option 字母→value 映射和完整选项列表，供详情页答案收集时使用
        option_map = get_option_value_map(driver, qtype)
        options_list = get_options_list(driver, qtype)

        question_order_map.append({
            "index": idx,
            "question_id": int(card_id),
            "option_map": option_map,
            "options": options_list,
        })

        question_text = get_question_text(driver)

        known_q = get_question(conn, int(card_id))
        known_answers = known_q.answers if known_q and known_q.has_answer else None

        answer_question(driver, qtype, known_answers=known_answers)
        short_sleep(0.5)

        # 确认作答已注册，最多重试 5 次
        answered = False
        for retry in range(5):
            if check_card_answered(driver, card_id):
                answered = True
                break
            short_sleep(0.8)
        if not answered:
            logger.warning("题目 %d (question_id=%s) 作答后未标记为已完成", idx + 1, card_id)

        # 题型组最后一题（单选→多选 / 多选→判断 / 判断→结束）：页面可能自动切走，额外等待
        is_section_end = (idx == len(card_ids) - 1) or (card_ids[idx + 1]["type"] != qtype)
        if is_section_end:
            short_sleep(1.0)

    # 4.4 提交试卷
    if not submit_exam(driver):
        return

    # 4.5 查看考试详情并收集答案
    if not click_view_detail(driver):
        return

    short_sleep(1)

    collected = collect_answers_from_detail(driver, question_order_map, lesson_id)
    for item in collected:
        upsert_question(
            conn,
            question_id=item["question_id"],
            lesson_id=item["lesson_id"],
            qtype=item["type"],
            question_text=item["question_text"],
            answer_values=item["answer_values"],
            options=item.get("options"),
        )


def process_all_lessons(driver: webdriver.Chrome, conn) -> dict:
    """遍历处理所有课程，循环直到全部达到终止条件或触发上限。

    Returns:
        汇总信息字典。
    """
    cfg = get_config()

    while True:
        lessons = get_lesson_list(driver)
        if not lessons:
            logger.info("无可用课程，流程结束")
            break

        all_done = True
        for lesson_info in lessons:
            lesson_id = lesson_info["lesson_id"]

            upsert_lesson(
                conn,
                lesson_id=lesson_id,
                title=lesson_info.get("title", ""),
                max_score=lesson_info.get("max_score", 0),
                attempt_count=lesson_info.get("attempt_count", 0),
                course_name=lesson_info.get("course_name", ""),
            )

            from database import get_lesson
            stored = get_lesson(conn, lesson_id)
            if stored is None:
                continue

            logger.info(
                "课程 %d [%s]: 最高成绩=%d, 测试次数=%d",
                lesson_id, stored.title, stored.max_score, stored.attempt_count,
            )

            if stored.is_completed:
                logger.info("课程 %d 已达标 (>=100分 且 次数>=%d)，跳过", lesson_id, cfg.minimum_tries)
                continue

            if stored.attempt_count >= cfg.max_tries_per_lesson:
                logger.warning("课程 %d 已达最大尝试次数 %d，跳过", lesson_id, cfg.max_tries_per_lesson)
                continue

            all_done = False
            logger.info("开始处理课程 %d (当前第 %d 次尝试)", lesson_id, stored.attempt_count + 1)

            try:
                process_one_lesson(driver, conn, lesson_id)
            except (TimeoutException, NoSuchElementException) as e:
                logger.error("处理课程 %d 时发生异常: %s，跳过本次", lesson_id, e)
                driver.get(f"{cfg.base_url}/jjfz/lesson")
            except Exception as e:
                logger.error("处理课程 %d 时发生未预期异常: %s", lesson_id, e, exc_info=True)
                driver.get(f"{cfg.base_url}/jjfz/lesson")
            break  # 处理完一门课后退出 for，由外层 while 重新获取课程列表

        if all_done:
            logger.info("所有课程已达标，流程结束")
            break


def print_summary(conn) -> None:
    """输出汇总日志。"""
    lessons = conn.execute("SELECT * FROM lessons").fetchall()
    questions = conn.execute("SELECT COUNT(*) as cnt FROM questions WHERE answer_values IS NOT NULL AND answer_values != ''").fetchone()
    logger.info("========== 汇总 ==========")
    logger.info("总课程数: %d", len(lessons))
    logger.info("题库收集答案数: %d", questions["cnt"] if questions else 0)
    for row in lessons:
        logger.info(
            "  课程 %d [%s]: 最高成绩=%d, 测试次数=%d",
            row["lesson_id"], row["title"], row["max_score"], row["attempt_count"],
        )
    logger.info("==========================")


def main() -> None:
    setup_logging()
    cfg = get_config()
    logger.info("===== 党旗飘飘自动答题脚本启动 =====")
    logger.info(
        "配置: base_url=%s, auto_submit=%s, minimum_tries=%d, max_tries=%d, headless=%s",
        cfg.base_url, cfg.auto_submit, cfg.minimum_tries, cfg.max_tries_per_lesson, cfg.headless,
    )

    conn = get_connection()
    init_db(conn)

    driver: Optional[webdriver.Chrome] = None
    try:
        driver = create_driver()
        ensure_login(driver)
        process_all_lessons(driver, conn)
        print_summary(conn)
    except KeyboardInterrupt:
        logger.info("用户中断运行")
    except Exception as e:
        logger.error("脚本运行异常: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        if driver is not None:
            driver.quit()
            logger.info("浏览器已关闭")
        conn.close()
        logger.info("数据库连接已关闭")
        logger.info("===== 脚本结束 =====")


if __name__ == "__main__":
    main()
