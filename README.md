# AI 辅助剧本创作工具

将小说文本（≥3 章）自动转换为结构化 YAML 剧本，支持电影、电视剧、舞台剧、动画。

## 三步上手

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 选择 AI 后端（三选一）

**我该选哪个？**

| 方案 | 效果 | 需要什么 | 花费 |
|------|------|----------|------|
| **Claude API**（推荐） | 最好，中文理解强 | 申请 API Key | $2-5/次 |
| **LM Studio**（免费） | 中等，受本地模型影响 | 安装 LM Studio + 下载模型 | 免费 |
| **OpenAI GPT** | 好 | 申请 API Key | $0.5-1/次 |

#### 方案 A：Claude API（推荐，效果最好）

```bash
export SCRIPT_TOOL_ANTHROPIC_API_KEY="sk-ant-..."
# 其余用默认值，无需额外设置
```

API Key 在 [console.anthropic.com](https://console.anthropic.com) 申请。

#### 方案 B：LM Studio（免费，本地运行）

1. 下载安装 [LM Studio](https://lmstudio.ai)
2. 在 LM Studio 里搜索下载一个中文好的模型，比如 **Qwen3-14B** 或 **Qwen2.5-7B-Instruct**
3. 加载模型后，切到 **Developer** 标签，点 **Start Server**（默认端口 1234）

```bash
export SCRIPT_TOOL_AI_PROVIDER=local
export SCRIPT_TOOL_AI_MODEL=qwen2.5-7b-instruct   # 改成你加载的模型名
```

> LM Studio 默认在 `localhost:1234` 提供 API，项目已预设此地址。

#### 方案 C：OpenAI GPT

```bash
export SCRIPT_TOOL_OPENAI_API_KEY="sk-..."
export SCRIPT_TOOL_AI_PROVIDER=openai
export SCRIPT_TOOL_AI_MODEL=gpt-4o
```

### 3. 启动

```bash
# Windows / WSL 用户先设置数据库路径（重要！）
export SCRIPT_TOOL_DATABASE_URL="sqlite:///C:/Users/<你的用户名>/script_tool.db"

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

打开浏览器访问 **http://localhost:8000**。

---

## 使用流程

进入首页后，从左到右三步走：

### 新建项目 → 导入小说 → 生成剧本

1. 点 **新建项目**，填项目名、选择剧本类型（电影/电视剧/动画等）
2. 在项目工作台上传 `.txt` / `.docx` / `.md` 文件，或直接粘贴小说文本（至少要有 3 章，比如"第一章""第二章""第三章"）
3. 点 **一键生成**（6 个阶段自动跑完），或点 **分步生成**（每个阶段完成后暂停，可以审查 AI 的中间结果再继续）

### 分步生成模式

分步模式下，Stage 1/2/3 完成后会自动暂停，展示 AI 识别的人物、情节、场景结构：

- **Stage 1** — 每章识别出哪些人物、地点、情节事件 → 检查有没有漏人或认错角色
- **Stage 2** — 跨章节合并去重，整理人物关系图 → 调整关系、补充遗漏
- **Stage 3** — 设计剧本场景列表 → 调整场景划分，增删合并场景

审查满意后点 **继续** 进入下一阶段。也可以点 **跳过审查，直接完成** 让剩余阶段自动跑完。

### 查看结果

流水线跑完后，结果面板会出现生成的 YAML 剧本。可以：
- 点 **查看/编辑剧本** 在线预览
- 点 **下载 YAML** 保存到本地

---

## 配置参考

所有配置都通过环境变量，不设就用默认值：

| 变量 | 默认值 | 作用 |
|------|--------|------|
| `SCRIPT_TOOL_AI_PROVIDER` | `claude` | 选哪个 AI：`claude` / `openai` / `local` |
| `SCRIPT_TOOL_AI_MODEL` | `claude-sonnet-4-6` | 模型名（用 local 时改成 LM Studio 里加载的模型） |
| `SCRIPT_TOOL_ANTHROPIC_API_KEY` | — | Claude API Key |
| `SCRIPT_TOOL_OPENAI_API_KEY` | — | OpenAI API Key |
| `SCRIPT_TOOL_LOCAL_LLM_URL` | `http://localhost:1234/v1` | 本地模型 API 地址 |
| `SCRIPT_TOOL_LOCAL_LLM_API_KEY` | `not-needed` | 本地模型 API Key（LM Studio 不验证） |
| `SCRIPT_TOOL_DATABASE_URL` | `sqlite:///storage/db.sqlite` | 数据库位置 |

---

## 常见问题

**Q: WSL 下启动后数据库报错 "database is locked"？**
A: 设置数据库路径到 Windows 本机目录：
```bash
export SCRIPT_TOOL_DATABASE_URL="sqlite:///C:/Users/<你的用户名>/script_tool.db"
```

**Q: 用 LM Studio 时提示连接失败？**
A: 检查三个点：
1. LM Studio 的 Server 是否已启动（Developer 标签 → Start Server）
2. 端口默认 1234，不要改
3. 模型名要和 LM Studio 里加载的一致

**Q: 一键生成跑到一半报错了？**
A: 切到分步模式重试——分步模式每步都有缓存，之前已完成的不需要重新跑。

**Q: 分步模式下 Stage 1/2/3 显示 "请先运行 Stage X"？**
A: 按顺序来，先跑 Stage 0，再跑 Stage 1，以此类推。

**Q: 一次能处理多长的小说？**
A: 建议 20 章以内、50 万字以内。超长的建议分成多个项目分批处理。
