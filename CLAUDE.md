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
python -m py_compile config.py models.py utils.py database.py scraper.py main.py
```

## Environment variables (.env)

| Variable | Purpose | Default |
|---|---|---|
| `DQPP_BASE_URL` | Root domain of the platform (e.g. `http://rdjy.upc.edu.cn`) — the script appends `/jjfz/lesson` internally | **Required** |
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
- **`database.py` uses only parameterized SQL.** The `conn` is passed in from `main.py`. SQLite connection uses WAL journal mode for better concurrent read performance.
- **`Config` is a frozen-dataclass singleton** — `get_config()` caches the instance after first call. All fields are read-only.
- **No `WebElement` references are stored across page navigations** — they go stale. Use `lesson_id` + CSS selectors to re-locate elements each time.
- **`process_all_lessons` breaks after each `process_one_lesson`** so the outer `while True` re-fetches fresh `get_lesson_list()` elements. On exception, it navigates back to `{base_url}/jjfz/lesson` to reset page state before the next iteration.

### Lesson list HTML structure (from exploration)

Each `<li>` in `ul.lesson_c_ul` has this structure:
```html
<li>
  <a href="/jjfz/lesson/lecture?lesson_id=451">
    <div class="lesson_ul_title">
      <h2>第一讲</h2>
      <p>中国共产党的发展历程</p>
    </div>
  </a>
  <dl class="lesson_center_dl">
    <dd>必读课件1</dd>           <!-- course_name — NO <dt> exists! -->
    <dd>需完成必读课件1</dd>
    <dd>测试次数：<span>5 次</span></dd>
    <dd>最高成绩：40 分</dd>
  </dl>
  <a class="self_text" href="...?lesson_id=451">开始自测</a>
</li>
```

Key: there is **no `<dt>` element** — title is parsed from `.lesson_ul_title h2` + `p`, course_name from the first `<dd>`.

### Login flow (scraper.py `ensure_login`)

1. `driver.get(base_url)` → redirects to `/login/#/guide` (Vue SPA)
2. Click `//button[contains(text(),'统一身份认证登录')]` → redirects to `cas.upc.edu.cn`
3. Switch into `<iframe src*="login-normal">` (Vue/Vant UI app)
4. **JS injection** (not DOM click): `document.querySelector('#app').__vue__` → set `.username` / `.password` → call `.passwordLogin()`
5. Switch out of iframe, wait 5s, then `_verify_logged_in` does `driver.get(f"{base_url}/jjfz/lesson")` and checks for `ul.lesson_c_ul`

### Exam flow (scraper.py + main.py `process_one_lesson`)

1. `click_start_exam(driver, lesson_id)` — re-navigates to base_url, finds `<a.self_text[href*='lesson_id=X']>`, clicks it, waits for `.cont_right_num`
2. `get_question_card_ids(driver)` — traverses `.exam_num_lists` children: each `<h5>` sets the current type (单选题→single, 多选题→multi, 判断题→judge), each `<ul>` yields cards. Returns `[{id, type}, ...]` — type is determined statically from the card area, not from the dynamically-loaded content area
3. Click each card via JS `dispatchEvent` (more reliable than `click()`) → `wait_for_exam_content()` waits for `.answer_list` with visible `input` elements → record `option_map` (letter→value) via `get_option_value_map()` → check known answers → answer
4. Options are clicked via `_click_option_element()` which tries `<label for="id">` → ancestor `<li>` → direct click, because `<input>` is visually hidden
5. Submit: click `#submit_exam` → `.public_submit` in confirm dialog. **If `auto_submit=false`, `submit_exam` returns `False` immediately** after showing the confirm dialog — the exam is NOT submitted and no answers are collected that cycle.
6. Collect answers: click `.submit_btn2` → iterate `.error_sub` blocks in order → parse `正确答案：X` from `.sub_result span.sub_color` → map letters to values via the stored `option_map` (detail page inputs have **no `value` attribute** — the letter→value mapping recorded during answering is critical)
7. `upsert_question()` stores the real option values (e.g. `["215830"]`) in SQLite, enabling known-answer matching on subsequent runs

### Entity alignment (critical)

The exam detail page has **no `question_id`** and its `<input>` elements have **no `value` attribute** (they render as `<input type="radio" name="radio3">` with no value).

- During answering: record `[{index: 0-based, question_id: X, option_map: {"A": "215830", ...}}, ...]`
- During detail scraping: parse `正确答案：A` from `.sub_result span.sub_color` → use `option_map` to convert letter "A" → value "215830"
- The `.sub_result span.sub_color` text format: `正确答案：A` (single/judge) or `正确答案：ABD` (multi)

## Gotchas

- **Login fails silently**: the CAS Vue iframe may show captcha after failed attempts. `_verify_logged_in` retries once (2 total attempts), then raises `RuntimeError`. Check `.env` credentials if it fails.
- **`StaleElementReferenceException`**: All element references die after any `driver.get()` or page navigation. The code handles this by always re-fetching elements from the current page.
- **`ElementNotInteractableException`**: The radio/checkbox `<input>` elements on the exam page are CSS-hidden. The `_click_option_element()` helper clicks the visible parent instead.
- **`DQPP_BASE_URL` is the root domain** (e.g. `http://rdjy.upc.edu.cn`), not the full lesson-list path. The script appends `/jjfz/lesson` internally. If you include `/jjfz/lesson` in the env var, the script will produce broken double paths like `.../jjfz/lesson/jjfz/lesson`.
- **Implicit wait (5s)** is set in `create_driver()`. Combined with explicit `WebDriverWait` timeouts, failed element lookups can take `implicit_wait + explicit_timeout` seconds.
- **Multi-choice questions load ~16 seconds** on the exam page — the section transition from single→multi triggers slow AJAX. `wait_for_exam_content` has a 15s timeout and may fire a warning before content appears. The script continues anyway and usually recovers.
- **Detail page inputs have no `value` attribute** — they render bare `<input type="radio">`. Answer collection relies entirely on parsing `正确答案：A` from `.sub_result span.sub_color` text and mapping letters to values via the `option_map` recorded during answering.
- **Unanswered questions show no correct answer** on the detail page. If timing issues cause a question to go unanswered, that question's answer cannot be collected in that cycle.
