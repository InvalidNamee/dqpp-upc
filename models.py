"""数据类定义 —— Lesson、Question 等，便于类型提示与数据传递。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Lesson:
    lesson_id: int
    title: str = ""
    max_score: int = 0
    attempt_count: int = 0
    course_name: str = ""
    last_updated: str = ""

    @property
    def is_completed(self) -> bool:
        """成绩 100 且尝试次数满足最低要求时视为已完成。"""
        from config import get_config

        cfg = get_config()
        return self.max_score >= 100 and self.attempt_count >= cfg.minimum_tries


@dataclass
class Question:
    question_id: int
    lesson_id: int
    type: str  # 'single', 'multi', 'judge'
    question_text: str = ""
    answer_values: str = ""  # JSON string
    options: str = ""  # JSON string, 所有选项 [{"label":"A","text":"...","value":"..."}]

    @property
    def answers(self) -> Any:
        import json

        return json.loads(self.answer_values) if self.answer_values else None

    @property
    def has_answer(self) -> bool:
        return bool(self.answer_values)

    @property
    def options_list(self) -> Any:
        import json

        return json.loads(self.options) if self.options else None
