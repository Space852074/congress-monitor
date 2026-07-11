# Congress Monitor

美国国会委员会信息监控工具。项目会抓取众议院、参议院委员会公开信息与官方听证会预告，翻译为中文，合并重复来源，并写入 Notion 数据库。

## 功能

- 并发抓取众议院和参议院委员会公开信息。
- 汇集 `senate.gov`、`house.gov` 与 `docs.house.gov` 的官方听证会预告。
- 对同一场听证会进行合并，保留多个官方来源链接。
- 自动翻译标题和摘要；翻译或抓取失败时自动重试。
- 写入前按链接和唯一键去重，避免 Notion 产生重复页面。
- 可打包为单文件 Windows 程序，无需日常手动运行 Python。

## 首次配置

1. 将 `config.local.env.example` 复制为 `config.local.env`。
2. 在 `config.local.env` 填入 Notion Integration Token 和 Database ID。
3. 确认 Notion 数据库已将 Integration 连接到该数据库。

`config.local.env` 仅保存在本机，已被 Git 忽略。请勿把真实令牌写入代码、README 或提交记录。

## 日常运行

Windows 用户直接双击：

```text
CongressMonitor.exe
```

也可以运行 `run_all.bat`，它使用本地 Python 环境执行同一流程。

## 命令行参数

```powershell
# 只抓取众议院
.\CongressMonitor.exe --chamber house

# 抓取但不读取或写入 Notion
.\CongressMonitor.exe --no-notion

# 读取 Notion 并抓取，但不写入新页面
.\CongressMonitor.exe --dry-run

# 保留英文，不调用翻译服务
.\CongressMonitor.exe --skip-translate
```

## 从源码运行

需要 Python 3.9 或更高版本：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_all.py
```

## 重新生成 EXE

代码改动后，双击 `build_exe.bat`。构建结果会生成在 `dist\CongressMonitor.exe`，可复制到项目根目录供日常使用。

## 项目结构

```text
committees/          各委员会抓取器
core/                通用抓取与官方听证会聚合
optimized_pipeline.py 并发调度、合并、翻译重试和 Notion 写入
notion_writer.py     Notion API 写入器
translator.py        中文翻译器
run_all.py           Python 入口
CongressMonitor.exe  打包后的 Windows 入口（不提交到 Git）
```

## 安全说明

历史版本曾在本地文本和源码中保存过令牌。上传前已从代码中移除，并在 `.gitignore` 中排除。由于这些令牌一度以明文保存，建议你在 Notion 和 OpenAI 控制台撤销旧令牌、创建新令牌，再填写进 `config.local.env`。
