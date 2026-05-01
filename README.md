# UPC 党旗飘飘自动答题脚本 (dqpp-upc)

> Claude Code + DeepSeek V4 Pro 构建

使用 Selenium 自动化"党旗飘飘"在线培训平台的自测答题，自动积累题库，直到每门课达到 100 分。

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env          # 编辑 .env 填入用户名密码
python main.py
```

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DQPP_BASE_URL` | 平台根域名（如 `http://rdjy.upc.edu.cn`） | 必填 |
| `DQPP_USERNAME` | CAS 统一认证用户名 | 必填 |
| `DQPP_PASSWORD` | CAS 统一认证密码 | 必填 |
| `DQPP_AUTO_SUBMIT` | 是否自动交卷 | `false` |
| `DQPP_MIN_TRIES` | 每课最少尝试次数 | `1` |
| `DQPP_MAX_TRIES` | 每课最大尝试次数 | `20` |
| `DQPP_DB_PATH` | SQLite 数据库路径 | `./party_school.db` |
| `DQPP_HEADLESS` | 无头模式 | `false` |
| `DQPP_DRIVER_PATH` | chromedriver 路径（空=自动查找） | `""` |

## 工作流程

1. **自动登录** — CAS 统一认证，JS 注入凭据绕过 Vue DOM 不稳定问题
2. **遍历课程** — 检查每门课的最高成绩和测试次数，达标则跳过，超上限则警告
3. **逐题作答** — 通过答题卡 `<h5>` 分组推断题型（单选/多选/判断），已知答案直接匹配，未知随机选择
4. **提交并收集** — 提交试卷后从考试详情页 `.sub_result` 解析"正确答案：ABD"格式，结合作答时记录的选项映射还原真实 option value
5. **循环** — 直到所有课程 ≥100 分且满足最低尝试次数

## 项目结构

```
config.py      # 环境变量与 frozen-dataclass 配置单例
models.py      # Lesson / Question 数据类
utils.py       # WebDriverWait 封装、安全查找、数字提取
database.py    # SQLite CRUD（WAL 模式，参数化 SQL）
scraper.py     # Selenium 页面交互（不操作数据库）
main.py        # 主工作流编排
```

## 数据库

SQLite `party_school.db`，跨会话复用：

- `lessons` — 课程成绩、测试次数、完成状态
- `questions` — 题库：题目 ID、题型、题干、正确答案（JSON 数组）、全部选项（JSON 数组，含 label/text/value）

## 核心机制

- **题型推断**：从答题卡区域的 `<h5>` 标签（单选题/多选题/判断题）静态推断，不依赖内容区动态加载
- **跳转验证**：点击答题卡后检查 `.answer_list` / `.answer_list_box` 中是否有已选中选项——无选中项 = 新题已加载。若选项未渲染或仍有已选中的旧选项，重试点击（最多 10 次，间隔 1.5s）
- **选项容器**：单选/判断题选项在 `.answer_list`，多选题选项在 `.answer_list_box`，结构不同——多选 `<input>` 是容器直接子元素，文本通过 `nextSibling` 提取
- **答案收集**：考试详情页的 `<input>` 无 `value` 属性，通过解析 `.sub_result span` 的"正确答案：A"文本，结合作答时记录的字母→value 映射还原真实 option value
- **答案覆盖**：新爬到的答案直接覆盖数据库旧值，避免早期错误数据导致一直答错
- **日志**：同时输出到终端和 `dqpp.log` 文件

## 注意事项

- 需要 Chrome 浏览器和匹配版本的 chromedriver
- 登录使用 CAS 统一认证，暂不支持验证码
- `DQPP_BASE_URL` 填写根域名即可（如 `http://rdjy.upc.edu.cn`），脚本内部拼接 `/jjfz/lesson`，目前只测试过积极分子的答题，推测修改 `jjfz` 可以兼容发展对象等
- 未作答的题目在考试详情页不会展示正确答案，确保每题都成功作答才能完整收集题库
