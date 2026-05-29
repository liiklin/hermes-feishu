# hermes-feishu

增强 Hermes Agent 飞书消息通道，支持卡片消息和表格渲染。

## 问题背景

Hermes Agent 内置的飞书通道使用 `post` 消息类型 + `tag: "md"` 发送 Markdown 内容。但飞书的 Markdown 组件仅支持语法子集，**不支持表格语法** (`| col | col |`)。这导致 LLM 生成的表格在飞书中无法正常渲染。

## 解决方案

本插件通过以下方式解决：

1. **`send_feishu_card` 工具** — 发送富文本卡片消息。自动检测 Markdown 中的表格语法，转换为飞书卡片 Table 组件。同样处理标题（`#`→emoji+加粗）和块引用（`>`→代码块包裹）。
2. **`send_feishu_table` 工具** — 直接发送结构化表格数据（headers + rows）。
3. **`post_api_request` 钩子** — 捕获每次 API 调用的 model/usage/duration，供底部状态栏使用。
4. **`transform_llm_output` 钩子** — 在最终 LLM 回复末尾追加模型/耗时状态栏。
5. **Gateway 自动卡片包装** — 插件自动部署一个 `gateway:startup` 钩子（`feishu-card-wrapper`），将所有飞书出站文本消息通过 `card_patcher.py` 包装为交互式卡片，解决飞书 Post 不支持标题和表格的问题。

## 快速安装

### 1. 环境准备

- Python 3.10+
- Hermes Agent 已安装并配置飞书平台
- 飞书开放平台应用（需要 App ID 和 App Secret）

### 2. 安装插件

```bash
hermes plugins install arkseek/hermes-feishu
```

### 3. 配置环境变量

**⚠️ 重要：凭证必须配置在 `~/.hermes/.env` 文件中，否则插件工具不会加载。**

```bash
# 编辑 Hermes 环境变量文件
nano ~/.hermes/.env

# 添加以下内容
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx

# 可选：设置默认 chat_id（用于 Hermes 未传递 chat_id 的情况）
# HERMES_FEISHU_CHAT_ID=oc_xxxxxxxxxxxxxxxxxxxxxxxx
```

#### 关于 HERMES_FEISHU_CHAT_ID

插件通过多级来源自动确定目标会话：

1. 工具调用时显式传递的 `chat_id` 参数
2. Hermes 会话上下文（gateway 自动注入）
3. `HERMES_FEISHU_CHAT_ID` 环境变量（回退默认值）

多会话场景下，gateway 会自动传递当前聊天会话的 `chat_id` 给插件，通常无需手动配置。

**如需要手动指定**：

```bash
# 编辑 Hermes 环境变量文件
nano ~/.hermes/.env

# 添加以下内容
HERMES_FEISHU_CHAT_ID=oc_xxxxxxxxxxxxxxxxxxxxxxxx
```

**如何获取 chat_id**：
1. 在飞书中发送消息给机器人
2. 查看 Hermes gateway 日志，搜索 `inbound message` 日志
3. 日志中的 `chat=oc_xxx` 即为 chat_id

### 4. 重启 Hermes

```bash
hermes gateway restart
```

重启后使用 `/plugins` 命令确认插件已加载。

## 使用方式

插件加载后，LLM 在飞书平台上会自动收到格式化指令。当需要展示表格时，LLM 会自动调用 `send_feishu_card` 或 `send_feishu_table` 工具。

### 工具参数

#### `send_feishu_card`

发送富文本卡片消息,支持 Markdown 内容和表格。

**参数:**
- `content` (必填): Markdown 内容,可包含表格
- `title` (可选): 卡片标题
- `chat_id` (可选): 目标会话 ID (通常自动检测)
- `template` (可选): 卡片配色模板 (默认: `blue`)
- `reaction` (可选): 发送后添加的表情反应 (例如: `👍`, `✅`, `🎉`)

**示例:**
```json
{
  "content": "| 姓名 | 年龄 |\n| --- | --- |\n| 张三 | 25 |\n| 李四 | 30 |",
  "title": "📊 数据表格",
  "template": "blue",
  "reaction": "✅"
}
```

#### `send_feishu_table`

发送结构化表格数据。

**参数:**
- `headers` (必填): 列标题数组
- `rows` (必填): 数据行数组
- `title` (可选): 卡片标题
- `chat_id` (可选): 目标会话 ID
- `template` (可选): 卡片配色模板
- `reaction` (可选): 发送后添加的表情反应

**示例:**
```json
{
  "headers": ["姓名", "年龄"],
  "rows": [["张三", "25"], ["李四", "30"]],
  "title": "📊 数据表格",
  "reaction": "👍"
}
```

### 示例：Markdown 表格

LLM 生成包含表格的内容时会自动调用：

```
用户: 帮我对比一下这两个方案

LLM 调用 send_feishu_card:
  content: |
    | 对比项 | 方案A | 方案B |
    | --- | --- | --- |
    | 成本 | ¥1000 | ¥2000 |
    | 周期 | 2周 | 1周 |
    | 风险 | 低 | 中 |
```

飞书中会渲染为带颜色标题的卡片消息，表格使用飞书 Table 组件。

### 示例：结构化表格

LLM 可以直接使用结构化数据：

```
LLM 调用 send_feishu_table:
  headers: ["指标", "当前值", "目标值"]
  rows: [
    ["日活用户", "10,000", "15,000"],
    ["转化率", "3.2%", "5%"],
    ["NPS", "42", "60"]
  ]
```

## 卡片格式处理

飞书 Card 的 `markdown` 标签不支持 `##` 标题和 `>` 块引用语法，插件在发送卡片前自动做以下转换：

| 原始 Markdown | 卡片中的渲染效果 |
|---|---|
| `# 标题` | 卡片标题栏 → `📌 标题`，正文 → `**📌 标题**` |
| `## 标题` | `**📍 标题**` |
| `### 标题` | `**🔹 标题**` |
| `#### 标题` | `**🔸 标题**` |
| `##### 标题` | `**▫️ 标题**` |
| `###### 标题` | `**▪️ 标题**` |
| `> 引用文字` | 连续引用行被包裹进灰底代码块 |

标题映射：
- H1 → 同时设为卡片标题栏（带 📌）和正文加粗显示
- H2-H6 → 正文中显示为 emoji + 加粗文字

块引用处理：
- 飞书 Card 不支持 `>` 语法，插件将相邻的引用行自动包裹成 ` ``` ` 代码块，在飞书中显示为带行号的灰底引用区块
- 独立的引用段落会被包裹为各自独立的代码块
- `send_message`（Post 通道）不受影响，Post 原生支持 `>` 渲染

此项处理在 `send_feishu_card` 工具和 gateway 自动卡片包装器（`card_patcher.py`）中均生效。

## 插件架构

```
src/hermes_feishu/
├── __init__.py      # 插件注册：工具 + 钩子
├── schemas.py       # 工具 Schema 定义
├── tools.py         # 工具处理器（标题/引用格式转换）
├── card_patcher.py  # Gateway 钩子：自动卡片包装（标题/引用格式转换）
├── card_builder.py  # 飞书卡片 JSON 构建
├── table_parser.py  # Markdown 表格解析
└── sender.py        # 飞书 API 发送层
```

## 飞书应用权限

插件需要以下飞书应用权限：

| 权限 | 权限标识 | 用途 |
| --- | --- | --- |
| 获取与发送单聊、群组消息 | `im:message` | 发送卡片消息 |
| 读取消息中的消息体内容 | `im:message:readonly` | 读取消息内容 |

## 开发

```bash
# 克隆仓库
git clone https://github.com/arkseek/hermes-feishu.git
cd hermes-feishu

# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -v

# 运行测试（带覆盖率）
pytest tests/ -v --cov=hermes_feishu
```

## 许可证

MIT License

## 更新日志

### v0.6.1 (2026-05-29)

**Bug 修复**
- 🐛 修复 footer 不显示：`stats` 模块移除 `os.environ` 跨进程传输，改用模块级变量。`os.environ` 在任何 OS 上都是进程私有，子进程修改不传回父进程，导致 `transform_llm_output` 读不到 `post_api_request` 写入的 API 统计。

**改进**
- 🔧 `plugin.yaml` 统一版本号，清除残留 `pre_llm_call` 引用
- 📝 README 更新"解决方案"章节，匹配实际使用的 `post_api_request` + `transform_llm_output` + gateway 自动卡片包装架构

### v0.6.0 (2026-05-29)

**新功能**
- 🎨 卡片格式自动转换：H1 提取为卡片标题栏，H1-H6 转为 `**emoji 文字**` 加粗显示
- 💬 块引用兼容处理：`>` 行自动包裹为代码块，以灰底带行号形式在卡片中显示
- 🔧 正则精确锚定：`##`/`###` 不再误匹配，H1 为唯一标题栏来源

**改进**
- 📝 新增"卡片格式处理"文档章节
- 🔄 `tools.py`（LLM 工具）和 `card_patcher.py`（Gateway 钩子）共享相同格式化逻辑

### v0.5.0 (2026-04-20)

- ✨ Gateway 自动卡片包装器（card_patcher.py）：自动将复杂 Markdown 回复包装为交互式卡片
- 📊 智能短消息回退：<80 字简单消息走原始 Post，不包装为卡片
- 🔧 自动部署钩子：扫描所有 Hermes profile 安装 gateway hook

**新功能**
- ✨ 添加消息 Reaction 支持：工具支持 `reaction` 参数，发送成功后自动添加表情反应
- 🔧 添加 `HERMES_FEISHU_CHAT_ID` 环境变量回退，解决 Hermes 未传递 chat_id 的问题

**Bug 修复**
- 🐛 修复飞书 Table 组件格式错误，正确使用字典列表格式
- 🐛 修复表格渲染失败问题（"table rows is invalid" 错误）

**改进**
- 📝 完善 README 文档，添加环境变量配置说明
- 🎨 改进错误消息，提供明确的解决方案

### v0.3.6 (之前)

- 初始版本
- 实现基本的卡片消息和表格渲染功能
