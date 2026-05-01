"""环境变量读取与配置管理 —— 加载 .env，导出常量，设置日志。"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def _bool_env(key: str, default: str = "false") -> bool:
    val = os.getenv(key, default).strip().lower()
    return val in ("true", "1", "yes", "on")


@dataclass(frozen=True)
class Config:
    base_url: str
    auto_submit: bool
    minimum_tries: int
    max_tries_per_lesson: int
    db_path: str
    headless: bool
    driver_path: str
    username: str
    password: str


_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config(
            base_url=os.getenv("DQPP_BASE_URL", "").strip(),
            auto_submit=_bool_env("DQPP_AUTO_SUBMIT", "false"),
            minimum_tries=int(os.getenv("DQPP_MIN_TRIES", "1")),
            max_tries_per_lesson=int(os.getenv("DQPP_MAX_TRIES", "20")),
            db_path=os.getenv("DQPP_DB_PATH", "./party_school.db").strip(),
            headless=_bool_env("DQPP_HEADLESS", "false"),
            driver_path=os.getenv("DQPP_DRIVER_PATH", "").strip(),
            username=os.getenv("DQPP_USERNAME", "").strip(),
            password=os.getenv("DQPP_PASSWORD", "").strip(),
        )
        if not _config.base_url:
            raise ValueError("环境变量 DQPP_BASE_URL 未设置，脚本无法启动")
        if not _config.username or not _config.password:
            raise ValueError("环境变量 DQPP_USERNAME 或 DQPP_PASSWORD 未设置，脚本无法自动登录")
    return _config


def setup_logging() -> None:
    fmt = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # 终端输出
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    # 文件输出
    file_handler = logging.FileHandler("dqpp.log", encoding="utf-8")
    file_handler.setFormatter(fmt)

    logging.basicConfig(level=logging.INFO, handlers=[console, file_handler])
