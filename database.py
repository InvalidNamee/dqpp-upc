"""数据库连接、建表、CRUD —— 所有数据库操作集中于此，均使用参数化 SQL。"""

import json
import logging
import sqlite3
from datetime import datetime
from typing import Optional

from config import get_config
from models import Lesson, Question

logger = logging.getLogger(__name__)


CREATE_LESSONS_TABLE = """
CREATE TABLE IF NOT EXISTS lessons (
    lesson_id INTEGER PRIMARY KEY,
    title TEXT,
    max_score INTEGER DEFAULT 0,
    attempt_count INTEGER DEFAULT 0,
    course_name TEXT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_QUESTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS questions (
    question_id INTEGER PRIMARY KEY,
    lesson_id INTEGER,
    type TEXT,
    question_text TEXT,
    answer_values TEXT
);
"""


def get_connection() -> sqlite3.Connection:
    cfg = get_config()
    conn = sqlite3.connect(cfg.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_LESSONS_TABLE)
    conn.execute(CREATE_QUESTIONS_TABLE)
    conn.commit()
    logger.info("数据库表初始化完成")


# ---- Lesson CRUD ----


def get_lesson(conn: sqlite3.Connection, lesson_id: int) -> Optional[Lesson]:
    row = conn.execute(
        "SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,)
    ).fetchone()
    if row is None:
        return None
    return Lesson(
        lesson_id=row["lesson_id"],
        title=row["title"] or "",
        max_score=row["max_score"] or 0,
        attempt_count=row["attempt_count"] or 0,
        course_name=row["course_name"] or "",
        last_updated=row["last_updated"] or "",
    )


def upsert_lesson(
    conn: sqlite3.Connection,
    lesson_id: int,
    title: str = "",
    max_score: int = 0,
    attempt_count: int = 0,
    course_name: str = "",
) -> None:
    existing = get_lesson(conn, lesson_id)
    if existing is None:
        conn.execute(
            "INSERT INTO lessons (lesson_id, title, max_score, attempt_count, course_name, last_updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (lesson_id, title, max_score, attempt_count, course_name, datetime.now().isoformat()),
        )
        logger.info("新增课程记录: lesson_id=%d, title=%s", lesson_id, title)
    else:
        conn.execute(
            "UPDATE lessons SET title=?, max_score=MAX(max_score, ?), attempt_count=?, "
            "course_name=?, last_updated=? WHERE lesson_id=?",
            (
                title or existing.title,
                max_score,
                attempt_count,
                course_name or existing.course_name,
                datetime.now().isoformat(),
                lesson_id,
            ),
        )
    conn.commit()


# ---- Question CRUD ----


def get_question(conn: sqlite3.Connection, question_id: int) -> Optional[Question]:
    row = conn.execute(
        "SELECT * FROM questions WHERE question_id = ?", (question_id,)
    ).fetchone()
    if row is None:
        return None
    return Question(
        question_id=row["question_id"],
        lesson_id=row["lesson_id"] or 0,
        type=row["type"] or "",
        question_text=row["question_text"] or "",
        answer_values=row["answer_values"] or "",
    )


def upsert_question(
    conn: sqlite3.Connection,
    question_id: int,
    lesson_id: int,
    qtype: str,
    question_text: str = "",
    answer_values: Optional[list] = None,
) -> None:
    existing = get_question(conn, question_id)
    answer_json = json.dumps(answer_values, ensure_ascii=False) if answer_values is not None else None

    if existing is None:
        conn.execute(
            "INSERT INTO questions (question_id, lesson_id, type, question_text, answer_values) "
            "VALUES (?, ?, ?, ?, ?)",
            (question_id, lesson_id, qtype, question_text, answer_json),
        )
        if answer_json:
            logger.info("新增题目: question_id=%d, type=%s, answer=%s", question_id, qtype, answer_json)
    else:
        if not existing.answer_values and answer_json:
            conn.execute(
                "UPDATE questions SET answer_values=?, question_text=?, type=? WHERE question_id=?",
                (answer_json, question_text or existing.question_text, qtype, question_id),
            )
            logger.info("补全题目答案: question_id=%d, answer=%s", question_id, answer_json)
        elif answer_json:
            pass
        else:
            conn.execute(
                "UPDATE questions SET question_text=?, type=? WHERE question_id=?",
                (question_text or existing.question_text, qtype, question_id),
            )
    conn.commit()
