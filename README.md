# Congress Monitor

美国国会委员会信息监控工具。项目会抓取众议院、参议院委员会公开信息与官方听证会预告，翻译为中文，合并重复来源，并写入 Notion 数据库。

## 功能

- 并发抓取众议院和参议院委员会公开信息。
- 抓取众议院和参议院各委员会网站发布的听证会与新闻信息。
- 对同一场听证会进行合并，保留多个官方来源链接。
- 自动翻译标题和摘要；翻译或抓取失败时自动重试。
- 写入前按链接和唯一键去重，避免 Notion 产生重复页面。
- 提供 Windows 批处理入口，自动选择可用的 Python 环境。

## 首次配置

1. 将 `config.local.env.example` 复制为 `config.local.env`。
2. 在 `config.local.env` 填入 Notion Integration Token 和 Database ID。
3. 确认 Notion 数据库已将 Integration 连接到该数据库。

`config.local.env` 仅保存在本机，已被 Git 忽略。请勿把真实令牌写入代码、README 或提交记录。

## 日常运行

Windows 用户直接双击：

```text
run_all.bat
```

## 命令行参数

```powershell
# 只抓取众议院
.\run_all.bat --chamber house

# 抓取但不读取或写入 Notion
.\run_all.bat --no-notion

# 读取 Notion 并抓取，但不写入新页面
.\run_all.bat --dry-run

# 保留英文，不调用翻译服务
.\run_all.bat --skip-translate
```

## 从源码运行

需要 Python 3.9 或更高版本：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_all.py
```

## 云端定时运行

GitHub Actions 工作流 `.github/workflows/cloud-scrape.yml` 每天按台北时间
`00:20`、`06:20`、`12:20` 和 `18:20` 自动运行，也支持在 Actions 页面手动启动。

仓库需要配置以下 Actions Secrets：

- `NOTION_TOKEN`：Notion Integration Token。
- `NOTION_DATABASE_ID`：目标 Notion 数据库 ID。

云端任务直接执行 `python run_all.py`，抓取结果仍写入 Notion。GitHub Actions
的定时任务可能因平台繁忙而延迟几分钟，并不保证整点立即开始。

## 项目结构

```text
committees/          各委员会抓取器
core/                通用抓取与官方听证会聚合
optimized_pipeline.py 并发调度、合并、翻译重试和 Notion 写入
notion_writer.py     Notion API 写入器
translator.py        中文翻译器
run_all.py           Python 入口
run_all.bat          Windows 日常启动入口
```

## 安全说明

历史版本曾在本地文本和源码中保存过令牌。上传前已从代码中移除，并在 `.gitignore` 中排除。由于这些令牌一度以明文保存，建议你在 Notion 和 OpenAI 控制台撤销旧令牌、创建新令牌，再填写进 `config.local.env`。
