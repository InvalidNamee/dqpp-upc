# 党旗飘飘自动答题脚本 (DQPP Auto Exam)

> [!NOTE]
> Claude Code + deepseek-v4-pro 构建

使用 Selenium 自动化“党旗飘飘”在线培训平台的自测答题，自动积累题库，直到每门课达到 100 分。

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env          # 编辑 .env 填入用户名密码
python main.py
```

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DQPP_BASE_URL` | 平台根域名 | 必填 |
| `DQPP_USERNAME` | CAS 统一认证用户名 | 必填 |
| `DQPP_PASSWORD` | CAS 统一认证密码 | 必填 |
| `DQPP_AUTO_SUBMIT` | 是否自动交卷 | `false` |
| `DQPP_MIN_TRIES` | 每课最少尝试次数 | `1` |
| `DQPP_MAX_TRIES` | 每课最大尝试次数 | `20` |
| `DQPP_DB_PATH` | SQLite 数据库路径 | `./party_school.db` |
| `DQPP_HEADLESS` | 无头模式 | `false` |
| `DQPP_DRIVER_PATH` | chromedriver 路径 | 自动查找 |

## 工作流程

1. **自动登录** —— 访问平台首页 → 点击"统一身份认证登录" → CAS iframe 注入凭据
2. **遍历课程** —— 检查每门课的成绩和测试次数，达标则跳过
3. **逐题作答** —— 已知答案直接作答，未知答案随机选择
4. **收集答案** —— 提交后从考试详情页提取正确答案，补全题库
5. **循环** —— 直到所有课程达到 100 分且满足最低尝试次数

## 项目结构

```
config.py      # 环境变量与配置
models.py      # Lesson / Question 数据类
utils.py       # WebDriverWait 封装等工具函数
database.py    # SQLite CRUD（参数化 SQL）
scraper.py     # Selenium 页面交互（不操作数据库）
main.py        # 主工作流编排
```

## 注意事项

- 需要 Chrome 浏览器和匹配版本的 chromedriver
- 题库存储在 SQLite `party_school.db` 中，可跨会话复用
- 登录使用 CAS 统一认证，不支持验证码
