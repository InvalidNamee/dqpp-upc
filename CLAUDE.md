# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

党旗飘飘 (Party School) auto-exam script. Uses Selenium + Chrome to automate:

1. **Login** — Unified CAS auth (`cas.upc.edu.cn`) via Vue.js iframe, with JS injection to bypass DOM instability
2. **Exam loop** — For each course: enter exam → answer questions (known answers from DB, random otherwise) → submit → scrape correct answers from detail page → repeat until score >= 100 and attempts >= minimum
3. **Knowledge base** — SQLite stores `lessons` (scores/attempts) and `questions` (correct answers keyed by system `question_id`)

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the script
python main.py

# Syntax check all files
python3 -c "import py_compile; [py_compile.compile(f, doraise=True) or print(f'{f}: OK') for f in ['models.py','config.py','utils.py','database.py','scraper.py','main.py']]"
```

## Environment variables (.env)

| Variable | Purpose | Default |
|---|---|---|
| `DQPP_BASE_URL` | Full lesson list URL (e.g. `http://rdjy.upc.edu.cn/jjfz/lesson`) | **Required** |
| `DQPP_USERNAME` | CAS unified auth username | **Required** |
| `DQPP_PASSWORD` | CAS unified auth password | **Required** |
| `DQPP_AUTO_SUBMIT` | Auto-submit exams (`true`/`false`) | `false` |
| `DQPP_MIN_TRIES` | Min attempts needed even after 100 score | `1` |
| `DQPP_MAX_TRIES` | Max attempts per course (safety limit) | `20` |
| `DQPP_DB_PATH` | SQLite database path | `./party_school.db` |
| `DQPP_HEADLESS` | Chrome headless mode | `false` |
| `DQPP_DRIVER_PATH` | chromedriver path (empty = auto from PATH) | `""` |

## Architecture

### Module dependency graph

```
config.py  (env vars, logging setup, singleton Config)
models.py  (Lesson, Question dataclasses)
utils.py   (WebDriverWait wrappers, safe find, number extraction)
database.py (SQLite: init tables, upsert_lesson, upsert_question, get_lesson, get_question)
scraper.py  (Selenium interactions only — no DB, no config writes)
main.py    (orchestration: create driver → login → loop courses → summary)
```

### Key design rules

- **`scraper.py` never touches the database.** It returns plain dicts/lists; `main.py` handles `upsert_question`/`upsert_lesson` calls.
- **`database.py` uses only parameterized SQL.** The `conn` is passed in from `main.py`.
- **No `WebElement` references are stored across page navigations** — they go stale. Use `lesson_id` + CSS selectors to re-locate elements each time.
- **`process_all_lessons` breaks after each `process_one_lesson`** so the outer `while True` re-fetches fresh `get_lesson_list()` elements.

### Login flow (scraper.py `ensure_login`)

1. `driver.get(base_url)` → redirects to `/login/#/guide` (Vue SPA)
2. Click `//button[contains(text(),'统一身份认证登录')]` → redirects to `cas.upc.edu.cn`
3. Switch into `<iframe src*="login-normal">` (Vue/Vant UI app)
4. **JS injection** (not DOM click): `document.querySelector('#app').__vue__` → set `.username` / `.password` → call `.passwordLogin()`
5. Switch out of iframe, wait 5s, then `_verify_logged_in` does `driver.get(base_url)` and checks for `div.w1150`

### Exam flow (scraper.py + main.py `process_one_lesson`)

1. `click_start_exam(driver, lesson_id)` — re-navigates to base_url, finds `<a.self_text[href*='lesson_id=X']>`, clicks it, waits for `.cont_right_num`
2. Click each `<li>` in `ul.exam_ul` — after each click, detect type from `.exam_list h5` text (单选→single, 多选→multi, 判断→judge)
3. For each question: if `questions` table has `answer_values` (JSON array), click matching options; else random select
4. Options are clicked via `_click_option_element()` which tries `<label for="id">` → ancestor `<li>` → direct click, because `<input>` is visually hidden
5. Submit: click `#submit_exam` → `.public_submit` in confirm dialog
6. Collect answers: click `.submit_btn2` → iterate `.error_sub` blocks in order → map by position to `question_order_map` (entity alignment — detail page has no `question_id`)
7. Correct answer values extracted from `<li class="result_cut">` inside `.exam_result2` (single/judge) or `.exam_result_box2` (multi)

### Entity alignment (critical)

The exam detail page has **no `question_id`**. The mapping relies on:
- During answering: record `[{index: 0-based, question_id: X}, ...]` from the card `<li id="X">` 
- During detail scraping: iterate `.error_sub` blocks in order, match by index to the recorded map

## Gotchas

- **Login fails silently**: the CAS Vue iframe may show captcha after failed attempts. If `_verify_logged_in` fails 3 times, check `.env` credentials.
- **`StaleElementReferenceException`**: All element references die after any `driver.get()` or page navigation. The code handles this by always re-fetching elements from the current page.
- **`ElementNotInteractableException`**: The radio/checkbox `<input>` elements on the exam page are CSS-hidden. The `_click_option_element()` helper clicks the visible parent instead.
- **`DQPP_BASE_URL` is the full path** to the lesson list (not the root domain). Do not append `/jjfz/lesson` to it.
- **Implicit wait (5s)** is set in `create_driver()`. Combined with explicit `WebDriverWait` timeouts, failed element lookups can take `implicit_wait + explicit_timeout` seconds.
