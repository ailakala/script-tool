# AI 辅助剧本创作工具

将 3 章以上小说文本自动转换为结构化剧本（YAML 格式），降低改编门槛，提升效率。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 设置 AI API Key（至少选一个）
export SCRIPT_TOOL_ANTHROPIC_API_KEY="sk-ant-..."    # Claude
export SCRIPT_TOOL_OPENAI_API_KEY="sk-..."           # GPT
# 或使用本地模型
export SCRIPT_TOOL_AI_PROVIDER="local"
export SCRIPT_TOOL_LOCAL_LLM_URL="http://localhost:8000/v1"
export SCRIPT_TOOL_LOCAL_LLM_API_KEY="your-key"      # 可选

# 启动
uvicorn app.main:app --reload
```

访问 http://localhost:8000

## 使用流程

1. **新建项目** → 填写剧本元信息（标题、来源、剧本类型）
2. **导入小说** → 上传 .txt/.docx/.md 文件，或直接粘贴文本（需 ≥ 3 章）
3. **一键生成** → AI 自动完成 6 阶段流水线转化
4. **查看结果** → 在线预览 YAML 剧本，支持下载

## 中间结果干预

AI 流水线在以下阶段支持暂停和人工介入：

| Stage | 内容 | 可干预 |
|-------|------|--------|
| 0 | 文本预处理（章节拆分） | — |
| 1 | 分章节分析（人物、地点、情节） | 审核 AI 识别结果 |
| 2 | 跨章节综合（去重、关系图） | 调整人物关系和情节线 |
| 3 | 剧本结构设计（场景列表） | 调整场景划分和结构 |
| 4 | 逐场内容生成 | — |
| 5 | YAML 组装 & 校验 | — |

## 剧本 YAML Schema

输出剧本遵循 [YAML Schema 规范](docs/script-yaml-schema.md)，包含：
- `meta` — 元数据
- `config` — 生成配置
- `characters` — 人物表（ID 体系、关系图）
- `scenes` — 场景列表（扁平结构、结构化 content 数组）
- `extensions` — 类型特定扩展（TV 分集大纲、电影节拍表等）

## 项目结构

```
app/
├── main.py              # FastAPI 入口
├── config.py            # 配置（环境变量驱动）
├── db.py                # 数据库连接
├── models.py            # ORM 模型（Project, PipelineRun, StageCache）
├── routes/
│   ├── pages.py         # SSR 页面路由
│   └── api.py           # REST API + SSE 流式
├── pipeline/
│   ├── executor.py      # 流水线调度器
│   ├── stage0_preprocess.py    # 文本预处理
│   ├── stage1_chapter_analysis.py  # 分章节分析
│   ├── stage2_cross_chapter_synthesis.py  # 跨章节综合
│   ├── stage3_script_structure.py   # 剧本结构设计
│   ├── stage4_scene_generation.py   # 逐场内容生成
│   └── stage5_assembly.py          # YAML 组装校验
├── ai/
│   ├── interface.py     # AI Provider 抽象接口
│   ├── claude.py        # Claude API
│   ├── openai.py        # OpenAI API
│   ├── local.py         # 本地模型（OpenAI 兼容）
│   └── factory.py       # 工厂函数
└── templates/           # Jinja2 模板
```

## 技术栈

- **Web**: FastAPI + Jinja2 SSR + HTMX
- **数据库**: SQLite (SQLAlchemy ORM)
- **AI**: Claude / GPT / 本地模型（通过统一接口切换）
- **测试**: pytest (35 tests)

## 测试

```bash
pytest tests/ -v        # 运行全部 35 个测试
```

## 配置

所有配置通过环境变量：

| 变量 | 默认 | 说明 |
|------|------|------|
| `SCRIPT_TOOL_AI_PROVIDER` | `claude` | AI 后端（claude/openai/local） |
| `SCRIPT_TOOL_AI_MODEL` | `claude-sonnet-4-6` | 模型名称 |
| `SCRIPT_TOOL_ANTHROPIC_API_KEY` | — | Claude API Key |
| `SCRIPT_TOOL_OPENAI_API_KEY` | — | OpenAI API Key |
| `SCRIPT_TOOL_LOCAL_LLM_URL` | `http://localhost:8000/v1` | 本地模型地址 |
| `SCRIPT_TOOL_LOCAL_LLM_API_KEY` | `not-needed` | 本地模型 API Key |
| `SCRIPT_TOOL_DATABASE_URL` | `sqlite:///storage/db.sqlite` | 数据库连接 |

## 限制

- 一次性处理上限: 20 章、50 万字
- 上传文件: 10MB
- 在线粘贴: 50 万字符
- 单次转换 LLM 成本: ~$2-5 (Claude) / ~$0.5-1 (GPT-4o)
