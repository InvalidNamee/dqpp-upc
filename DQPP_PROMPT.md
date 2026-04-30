# UPC 党旗飘飘自动答题脚本生成提示词

请使用 Python 编写一个自动化脚本，功能如下：
- 使用 Selenium 控制 Chrome 浏览器（需安装对应版本的 chromedriver）
- 使用 SQLite（内置 `sqlite3` 模块）存储课程信息与题库
- 通过 `python-dotenv` 加载环境变量
- 使用标准库 `logging` 模块输出详细运行日志

目标：自动爬取“党旗飘飘”党课自测成绩，自动答题并积累题库，直到每门课达到 100 分且满足最少尝试次数。

## 环境变量

在项目根目录创建 `.env` 文件，脚本通过 `dotenv` 加载。所有变量均有默认值或说明：

| 变量名 | 说明 | 默认值 | 备注 |
|--------|------|--------|------|
| `DQPP_BASE_URL` | 党课列表页面的完整 URL | 无，必须提供 | 例如 `http://example.com/jjfz/lesson` |
| `DQPP_AUTO_SUBMIT` | 是否自动提交试卷 | `false` | `true`/`false`。若为 `false`，在交卷前暂停等待人工确认（调试用） |
| `DQPP_MIN_TRIES` | 每门课程最少尝试次数（达到100分后仍需满足） | `1` | 整数 |
| `DQPP_MAX_TRIES` | 单门课程最大尝试次数（防止死循环） | `20` | 整数，达到上限后即使未达目标也会跳过该课，并记录警告日志 |
| `DQPP_DB_PATH` | SQLite 数据库文件路径 | `./party_school.db` | 可自定义 |
| `DQPP_HEADLESS` | 是否启用 Chrome 无头模式 | `false` | 调试时可设为 `false` 观察运行 |
| `DQPP_DRIVER_PATH` | chromedriver 可执行文件路径 | 空（自动从 PATH 查找） | 需与系统 Chrome 版本匹配 |

## 数据库设计

使用 SQLite3，创建以下两个表：

```sql
-- 课程信息表
CREATE TABLE IF NOT EXISTS lessons (
    lesson_id INTEGER PRIMARY KEY,
    title TEXT,
    max_score INTEGER DEFAULT 0,       -- 历史最高成绩
    attempt_count INTEGER DEFAULT 0,   -- 测试次数（源于页面显示）
    course_name TEXT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 题库表，存储正确答案
CREATE TABLE IF NOT EXISTS questions (
    question_id INTEGER PRIMARY KEY,   -- 页面中的题目ID（如答题卡 <li id="67761">）
    lesson_id INTEGER,
    type TEXT,                         -- 'single', 'multi', 'judge'
    question_text TEXT,
    answer_values TEXT                 -- JSON字符串，存储正确答案的选项value列表（单选/判断存单值，多选存数组）
);
```

> **说明**：`question_id` 来自答题卡中每道题的 `<li id="...">`，是题目在系统中的唯一标识；`lesson_id` 用于关联所属课程。

## 工作流详细步骤

### 1. 初始化
- 从 `.env` 加载环境变量，缺失必须项时脚本报错退出。
- 配置日志：`logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')`，后续关键节点均需写日志。
- 配置 Selenium WebDriver（若 `DQPP_DRIVER_PATH` 不为空则指定路径，否则使用系统默认）。
- 若 `DQPP_HEADLESS` 为 `true`，添加 `--headless` 选项。
- 连接 SQLite 数据库（自动创建文件），执行建表语句。
- 记录启动日志，输出当前配置。

### 2. 登录状态检查
- 访问 `DQPP_BASE_URL`。
- 检测页面是否存在 `<div class="w1150" style="margin-bottom:30px;">` 元素（已登录标志）。
- 若未找到该元素，输出日志提示“未检测到登录状态，请手动登录后按回车继续...”，等待用户按回车，刷新页面后重新检测，循环直到通过。

### 3. 获取课程列表
- 登录成功后，定位 `<div class="w1150" ...>` 下的 `<ul class="lesson_c_ul">`，获取所有 `<li>` 元素。
- 从每个 `<li>` 中提取 `lesson_id`（如“开始自测”链接中 `?lesson_id=xxx` 的参数值）。生成课程列表 `lesson_ids`。

### 4. 遍历处理每门课程
对每个 `lesson_id`，执行一个内部循环（见终止条件），日志记录当前课程 ID。

**4.1 刷新课程状态**
- 重新访问 `DQPP_BASE_URL`，等待列表加载。
- 定位该 `lesson_id` 对应的 `<li>`，从 `<dl class="lesson_center_dl">` 中解析：
  - 测试次数 X：从“测试次数：X 次”中提取数字。
  - 最高成绩 Y：从“最高成绩：Y 分”中提取数字。
- 同步数据库 `lessons` 表：
  - 若记录不存在，插入新行（含 `title`、`course_name`、`max_score=Y`、`attempt_count=X`）。
  - 若已存在，更新 `max_score` 为 max(库中值, Y)，`attempt_count` 为 X。
- **终止条件判断**：若 Y >= 100 **且** X >= `DQPP_MIN_TRIES`，则输出日志并跳过该课程（`continue`）。
- **防死循环判断**：若当前课程的内部循环次数（即尝试次数）已达到 `DQPP_MAX_TRIES`，则输出警告日志，跳过该课程。

**4.2 进入答题**
- 在当前 `<li>` 中点击“开始自测”链接 `<a class="self_text">`，等待新页面加载，直到 `.cont_right_num` 答题卡出现。

**4.3 逐题作答**
- 从答题卡 `<ul class="exam_ul">` 中获取所有 `<li>`（题号），按顺序依次点击。每次点击后等待对应 `.exam_list` 区域可见。
- 对于每个题目，解析并记录：
  - `question_id`：`<li id="...">` 的属性值。
  - 题目文本：从 `.exam_h2` 获取（**注意**：此处文本不含“【单选题】”等标记，只有题干本身）。
  - 题型：根据所在 `<h5>`（单选题/多选题/判断题）推断，存入变量。
  - 选项及各自的 `value` 属性（单选/判断用 `input[type=radio]`，多选用 `input[type=checkbox]`）。
- **答案选择逻辑**：
  - 查询 `questions` 表，若存在该 `question_id` 的记录：
    - 解析 `answer_values` JSON，按值勾选对应选项（单选/判断点击对应 radio；多选勾选所有匹配的 checkbox）。
  - 若无记录：
    - 随机作答：单选/判断随机选一个；多选随机选至少 1 个，最多全选。
  - 完成后，检查对应答题卡 `<li>` 的 class 是否变为 `exam_full`，确认已作答。同时输出日志说明此题使用的策略（“使用已知答案”或“随机作答”）。
  - **重要**：将当前题目在页面中的顺序（索引）及对应的 `question_id` 存储到一个列表中，供后续答案收集时做实体对齐（因为考试详情页中没有 `question_id`，需要用题号映射）。

**4.4 提交试卷**
- 点击“交卷”按钮 `<a id="submit_exam" class="exam_a_sub">交 卷</a>`。
- 等待确认框 `.public_cont` 出现。
- 根据 `DQPP_AUTO_SUBMIT`：
  - `true`：自动点击“我要提交”（`.public_submit`）。
  - `false`：输出日志提示“等待人工确认提交...”，暂停等待 Enter，然后点击。
- 提交后等待跳转至结果页。

**4.5 查看考试详情并收集正确答案（对齐实体）**
- 点击“查看考试详情”（`.submit_btn2`），等待 `.error_box_lists` 容器出现。
- 遍历所有 `.error_sub` 区块，**务必按页面顺序处理**（与答题时的题号顺序一致）。
- 对于每个 `.error_sub`：
  - 提取题号及题型：从 `.sub_title h3` 文本中解析出数字编号和题型标记（如“1、【单选题】”）。
  - **实体对齐关键步骤**：利用之前答题时保存的“题号→question_id”映射列表，根据当前 `.error_sub` 的题号，确定对应的 `question_id`。例如第 1 个 `.error_sub` 对应答题时第 1 道题的 `question_id`。
  - 提取正确答案：
    - 单选：在 `.exam_result2` 下找到所有 `<li>` 中带有 `class="result_cut"` 的选项，提取其内部 `<input>` 的 `value`。
    - 多选：在 `.exam_result_box2` 下同样查找所有 `class="result_cut"` 的 `<li>`，收集所有对应的 `value`。
    - 判断题同单选。
  - 将答案数据转换为 JSON 字符串（单选/判断存单个字符串，多选存数组字符串，如 `["217830","217831"]`）。
  - 更新/插入题库 `questions` 表：
    - 若对应 `question_id` 不存在，插入新记录，包含 `question_id`、`lesson_id`、题型 `type`、题目文本 `question_text`、`answer_values`。
    - 若已存在但答案字段为空（之前随机作答时未记录答案），则补全 `answer_values`（如果已有答案则保持不动）。
  - 输出日志：记录成功收集题目的 `question_id` 及正确答案。

**4.6 循环回到 4.1**
- 一次答题及答案采集完成后，跳转回课程列表页（或再次访问 `DQPP_BASE_URL`），重新执行 4.1 检查成绩与次数，决定是否继续。

### 5. 完成清理
- 所有课程处理完毕后，输出汇总日志（总课程数、每题收集答案数、每课最终成绩等）。
- 关闭浏览器（`driver.quit()`），关闭数据库连接，退出。

## 关键注意事项

1. **超时与等待**：全程使用显式等待（`WebDriverWait` + `expected_conditions`）而非固定 `time.sleep`，仅在必要处（如等待手动登录）使用 `input`。
2. **异常处理**：捕获 `NoSuchElementException`、`TimeoutException`、`StaleElementReferenceException` 等，记录错误日志并尝试重试或跳过当前操作，避免整体崩溃。
3. **实体对齐强调**：考试详情页的题目没有 `question_id`，必须使用**题号顺序**进行映射。步骤 4.3 中需记录下各题在页面中的序号及其 `question_id`，步骤 4.5 中按序读取详情页块，即可准确关联。切勿试图通过题目文本直接匹配，因为文本可能存在细微差异。
4. **题型标记注意**：答题页面的题干中不包含“【单选题】”等字样，而考试详情页的标题中含有。因此在实际解题过程中，题型应通过答题卡中 `<h5>` 分类推断，详情页主要用于收集答案。
5. **防死循环上界**：每门课程的内部循环次数达到 `DQPP_MAX_TRIES` 时必须强制退出该课程的循环，并记录警告日志，不得无限重试。此值默认 20，用户可在 `.env` 中调整。
6. **日志输出要求**：必须记录以下关键节点——
   - 登录状态检测结果
   - 每门课程的当前成绩/次数、是否满足终止条件
   - 每道题的作答方式（已知答案/随机）
   - 交卷操作
   - 答案收集的结果（每道题是否正确获取到答案）
   - 异常/重试信息
7. **数据库操作**：使用参数化 SQL，避免拼接字符串。每次更新后立即 `commit`，防止数据丢失。
8. **尊重服务端**：两次页面跳转间可加入较短等待（如 0.5~1 秒），但不要过快连续点击。

请严格按照上述需求生成完整、可运行的 Python 脚本，包含必要的导入、函数封装、详尽的注释和全面的错误处理。

## 代码结构要求（必须遵守）

**严禁将所有逻辑写入单个文件**。请严格按以下模块拆分，每个模块职责单一：

| 文件 | 职责 | 关键内容 |
|------|------|----------|
| `config.py` | 环境变量读取与配置管理 | 加载 `.env`，导出常量（URL、开关、路径等），设置日志 |
| `database.py` | 数据库连接、建表、CRUD | `get_connection()`、建表函数、`get_lesson()`、`upsert_question()` 等，均参数化 |
| `scraper.py` | Selenium 页面交互与解析 | 登录检查、获取课程列表、答题流程、提取答案，不直接操作数据库 |
| `models.py` （可选） | 数据类定义 | 使用 `dataclass` 定义 `Lesson`、`Question` 等，便于类型提示 |
| `main.py` | 主工作流编排 | 调用各模块，串联步骤 1~5，实现循环逻辑和异常处理 |
| `utils.py` （可选） | 通用工具函数 | 等待元素、解析数字、格式化日志等 |

**要求**：
- 每个 `.py` 文件包含明确的 `if __name__ == "__main__":` 仅用于测试（如有），入口统一为 `main.py`。
- 所有函数都添加类型注解和 docstring。
- 数据库操作全部放在 `database.py` 中，`scraper.py` 只负责 Selenium 交互并返回 Python 数据结构。
- 使用绝对导入（如 `from database import get_connection`）。

请根据以上模块图，生成完整、可运行的多文件项目代码，并附带 `requirements.txt`。