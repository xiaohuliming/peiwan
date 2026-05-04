# 嗯呢呗电竞 - KOOK 陪玩店系统

基于 Flask + MySQL + KOOK Bot 的陪玩店中控系统，包含订单、礼物、财务、提现、抽奖、播报、用户/身份管理等功能。

## 主要功能

- 账号与身份管理：支持主角色 + 身份标签（老板/陪玩/客服可并存）
- 订单中心：建单、派单、报单、确认、退款、删除未付款订单
- 礼物中心：礼物配置、赠送/退款、礼物播报、礼物图片播报
- 财务中心：余额变动、提现申请与审批、双收款码（微信/支付宝）
- 播报管理：充值/消费/礼物/升级/抽奖等模板化播报
- 抽奖系统：后台抽奖 + 机器人互动抽奖（`/发布抽奖`、`/结束抽奖`）
- KOOK 机器人：私信通知、卡片按钮、常用命令（`/help`、`/roll`、`/提现` 等）
- 定时任务：订单自动确认、打卡超时处理、抽奖自动开奖、参与人数更新

## 技术栈

- Python 3.11
- Flask 3
- SQLAlchemy + Flask-Migrate（Alembic）
- MySQL（默认库名：`peiwan_admin`）
- APScheduler
- khl.py（KOOK Bot）

## 项目结构

```text
app/
  models/           数据模型
  views/            页面与接口蓝图
  services/         业务服务（订单、礼物、KOOK推送、抽奖等）
  templates/        前端模板
  static/           静态资源与上传目录
bot/
  bot.py            KOOK 机器人命令入口
migrations/         数据库迁移
run.py              Flask 启动入口
init_db_data.py     初始化演示数据脚本
```

## 环境准备

1. 创建并激活虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. 安装依赖

```bash
pip install -r requirements.txt
```

3. 准备 MySQL 数据库

```sql
CREATE DATABASE peiwan_admin CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

4. 配置环境变量（建议使用项目根目录 `.env`）

## 环境变量说明

| 变量名 | 是否必填 | 说明 |
|---|---|---|
| `SECRET_KEY` | 建议 | Flask 会话密钥 |
| `DATABASE_URL` | 建议 | 如：`mysql+pymysql://user:pass@127.0.0.1:3306/peiwan_admin` |
| `KOOK_TOKEN` | 若启用Bot必填 | KOOK 机器人 Token |
| `KOOK_BOT_ENABLED` | 可选 | `true/false`，`true` 时 Web 进程内自动启动 Bot 线程 |
| `PUBLIC_SITE_URL` | 建议 | 对外可访问域名，用于消息跳转链接 |
| `SITE_URL` | 可选 | 不填默认等于 `PUBLIC_SITE_URL` |
| `STORY_LLM_API_KEY` | 剧情AI必填 | AI 文字剧情 DeepSeek/OpenAI-compatible API Key |
| `STORY_LLM_MIN_VISIBLE_CHARS` | 可选 | 主线剧情单次最短正文，过短会触发一次结构化修复重试 |
| `STORY_LANGGRAPH_ENABLED` | 可选 | `true/false`，默认 `true`，启用 LangGraph 剧情流程编排 |
| `STORY_MEMORY_ENABLED` | 可选 | `true/false`，启用 mem0 长期记忆 |
| `STORY_MEMORY_BACKEND` | 可选 | `mem0_sdk` 或 `mem0_rest` |
| `MEM0_EMBEDDER_PROVIDER` | 可选 | 默认 `fastembed`，本地向量模型；也可改 `openai` 等远程 embedding |
| `MEM0_EMBEDDER_API_KEY` | 远程embedding时必填 | 向量模型 API Key；DeepSeek 只做 LLM，不负责 embedding |
| `MEM0_QDRANT_URL` / `MEM0_QDRANT_PATH` | 可选 | Qdrant 远程地址或本地嵌入式存储路径 |
| `SSL_CERT_FILE` | 可选 | 证书链路径（服务器证书问题时用） |
| `REQUESTS_CA_BUNDLE` | 可选 | 同上 |
| `SSL_CERT_DIR` | 可选 | 证书目录 |

示例：

```env
SECRET_KEY=replace-me
DATABASE_URL=mysql+pymysql://root:password@127.0.0.1:3306/peiwan_admin
KOOK_BOT_ENABLED=true
KOOK_TOKEN=your-kook-token
PUBLIC_SITE_URL=https://www.ennb.xin
SITE_URL=https://www.ennb.xin
```

## AI 剧情长期记忆（mem0，可选）

剧情 Bot 的 `/游戏 剧情 继续` 已接入 LangGraph 编排层：`prepare_context -> call_llm -> validate_payload -> persist_turn -> dispatch_side_effects`。这条链路让上下文构建、LLM 生成、JSON 校验、数据库落库、私信与记忆写入各自成为清晰节点；如果 LLM 或校验失败，本轮不会写入剧情进度。

剧情 Bot 已预留 mem0 适配层，默认关闭。开启后，每轮剧情会先按 KOOK 用户召回长期记忆，并在剧情成功生成后写入 mem0；记忆层失败不会阻断主线剧情。

剧情生成已加结构化校验：LLM 必须返回 `visible_text`、`state_updates`、`suggested_choices`，并可返回 `narrative_events`。如果 JSON 结构不合格、正文过短、角色 id 不合法，系统会把错误原因发回 LLM 修复一次；仍失败则本轮不推进剧情，避免污染玩家状态。

剧情硬状态由数据库控制：`story_hard_states` 保存玩家当前位置、当前任务、任务进度、物品和 NPC 状态。LLM 不能只靠正文“宣布”获得道具或切换地点，必须通过 `state_updates.hard_state_updates` 提交结构化变更，后端校验通过后才会落库。

Chapter 0 已加入章节状态机：Prompt 会携带 `chapter_scene_rules`，后端会校验 `current_scene`、`hard_state_updates.location`、任务 id 和章节推进。非法跳场景、跳章节或直接进入结局会被拒绝，并触发一次结构化修复重试；仍不合规则本轮不落库。

轻量试点推荐 `mem0_sdk` + 本地 Qdrant path + FastEmbed。这个方案不需要 Docker，也不需要额外 embedding key，首次运行会下载本地向量模型。

```bash
pip install -r requirements.txt
```

`.env` 示例：

```env
STORY_MEMORY_ENABLED=true
STORY_MEMORY_BACKEND=mem0_sdk
MEM0_LLM_PROVIDER=deepseek
MEM0_LLM_MODEL=deepseek-v4-flash
MEM0_LLM_BASE_URL=https://api.deepseek.com
MEM0_EMBEDDER_PROVIDER=fastembed
MEM0_EMBEDDER_MODEL=BAAI/bge-small-zh-v1.5
MEM0_EMBEDDER_DIMS=512
MEM0_VECTOR_PROVIDER=qdrant
MEM0_QDRANT_PATH=instance/qdrant
MEM0_HISTORY_DB_PATH=instance/mem0_history.db
```

如果你要用独立 Qdrant 服务：

```bash
docker compose -f docker-compose.mem0.yml up -d
```

然后删除 `MEM0_QDRANT_PATH`，改用 `MEM0_QDRANT_HOST=127.0.0.1` 和 `MEM0_QDRANT_PORT=6333`。

如果后续改成独立 mem0 REST 服务，把 `STORY_MEMORY_BACKEND=mem0_rest`，并配置 `MEM0_API_URL` 与 `MEM0_API_KEY` 即可。

检查记忆层配置：

```bash
.venv/bin/python scripts/story_memory_check.py
.venv/bin/python scripts/story_memory_check.py --smoke
```

Bot 内可用 `/游戏 剧情 状态` 查看 Mem0 开关状态，也可以用 `/游戏 剧情 长期记忆 关键词` 查询当前 KOOK 用户自己的长期记忆召回结果。

## 数据库迁移

```bash
export FLASK_APP=run.py
flask db upgrade
```
说明：仓库已包含 `migrations/`，常规部署只需要执行 `flask db upgrade`，不要重复 `flask db init`。

## 初始化演示数据（可选）

```bash
python init_db_data.py
```

脚本会创建演示账号和测试数据（含默认管理员、项目、订单、礼物等）。
默认管理员（仅演示环境）：`admin / 123456789`。

## 本地启动

方式1：

```bash
flask --app run.py run --host 0.0.0.0 --port 5000
```

方式2：

```bash
python run.py
```

访问：`http://127.0.0.1:5000`

## KOOK Bot 运行方式

### 方式 A（推荐）：跟随 Flask 进程自动启动

- 设置 `KOOK_BOT_ENABLED=true`
- 启动 Web 后会在后台线程启动 Bot

### 方式 B：独立进程运行 Bot

```bash
python bot/bot.py
```

注意：不要同时用 A/B 两种方式，否则可能出现重复响应。

## 定时任务

项目启动后会自动注册以下任务：

- 每 5 分钟：自动确认到期订单
- 每 10 分钟：打卡超时处理
- 每 1 小时：VIP 批量升级检查
- 每 5 秒：到期抽奖自动开奖
- 每 10 秒：抽奖参与人数兜底刷新

## 常用机器人命令

- `/help`：查看命令列表
- `/钱包`：查看余额
- `/结单 订单号 时长`：陪玩申报结单
- `/确认 订单号`：老板确认订单
- `/提现 [金额]`：发起提现（金额可不填，支持引导到网页）
- `/取消提现`：取消待上传收款码提现
- `/roll 总点数 抽几个点`：随机掷点
- `/游戏`：打开游戏菜单，包含猜词、乱序词、密码色、21 点、四子棋、排行榜与《灰区档案》
- `/发布抽奖 中奖人数`：发起互动抽奖（30 分钟自动开奖）
- `/结束抽奖`：提前结束互动抽奖

## 部署建议（Gunicorn 示例）

1. 安装依赖并配置 `.env`
2. 执行迁移：`flask db upgrade`
3. 启动 Web：

```bash
gunicorn -w 2 -b 0.0.0.0:5000 run:app
```

4. 通过 Nginx 反代到公网域名
5. 确保上传目录可写：`app/static/uploads/`
6. 重启进程后验证：网页登录、`/help`、抽奖/礼物播报是否正常

## 常见问题

### 1) `/发布抽奖` 无响应

优先检查：

- `KOOK_TOKEN` 是否有效
- Bot 是否在运行（自动线程或独立进程）
- 服务器证书是否完整（必要时设置 `SSL_CERT_FILE`）

### 2) 页面 500（尤其分页）

优先检查：

- 迁移是否全部执行：`flask db upgrade`
- 线上代码与数据库版本是否一致
- 日志中是否存在字段缺失或外键错误

### 3) 机器人跳转链接指向 127.0.0.1

设置：

- `PUBLIC_SITE_URL`
- `SITE_URL`

为公网可访问地址（例如 `https://www.ennb.xin`）。

## 数据字段说明（货币）

- `m_coin`：嗯呢币（老板侧主余额）
- `m_coin_gift`：赠金
- `m_bean`：小猪粮（陪玩可提现余额）
- `m_bean_frozen`：冻结小猪粮

## 许可证

当前仓库未声明开源许可证，如需对外分发请补充 `LICENSE` 文件。
