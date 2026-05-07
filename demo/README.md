# VGD Memory OS — Graph-Document Hybrid Demo

> **由图引路，由文生智** · 一个面向 AI Agent 的混合记忆操作系统最小可运行原型

本 Demo 实现了 VGD（Vision–Gbrain–Document）记忆操作系统中的两大核心子系统 **Gbrain（左脑·知识图谱）** 与 **LLM-Wiki（右脑·实体百科）**，并通过一个 FastAPI 后端 + D3.js 前端把整条「文本摄入 → 记忆固化 → 混合检索 → 智能问答」链路完整跑通。

---

## 一、快速开始

### 1.1 环境要求

- Python ≥ 3.10
- 至少一个 **LLM API Key**（根据选择的提供商配置）：

| 提供商 | 环境变量 | 获取方式 |
|--------|---------|---------|
| Anthropic（默认） | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| OpenAI | `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| DeepSeek | `ANTHROPIC_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com) |

### 1.2 安装与启动

```bash
cd demo
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-xxx        # Linux/macOS — Anthropic
# set ANTHROPIC_API_KEY=sk-ant-xxx         # Windows
python run.py
```

打开浏览器访问 `http://localhost:8000` 即可看到三栏式 Demo 界面。

### 1.3 三步体验

1. **摄入知识** Tab → 点击「加载示例数据」按钮 → 系统会自动注入一段科技公司场景文本
2. 等待几秒（Claude Haiku 4.5 抽取三元组 + 生成 Wiki），左侧图谱自动绘制
3. **智能问答** Tab → 输入「Who founded OpenAI? Who invested in it?」→ 观察图遍历高亮 + Claude Opus 4.7 综合作答

### 1.4 启动配置选项

`run.py` 支持通过命令行参数或配置文件自定义服务运行地址和端口，并在启动前自动检测端口占用情况。

#### 命令行参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--host` | str | `0.0.0.0` | 服务监听地址 |
| `--port` | int | `8000` | 服务监听端口 |
| `--config` | str | `server_config.json` | JSON 配置文件路径 |
| `--no-reload` | flag | 启用热重载 | 禁用代码热重载 |
| `--auto-port` | flag | 无 | 端口被占用时自动分配可用端口 |

```bash
# 自定义地址和端口
python run.py --host 127.0.0.1 --port 8080

# 指定端口，被占用时自动分配可用端口
python run.py --port 9000 --auto-port

# 禁用热重载（生产环境推荐）
python run.py --no-reload

# 从自定义配置文件读取
python run.py --config my_server.json
```

#### 配置文件方式

创建 `server_config.json`（默认路径，可通过 `--config` 指定其他路径）：

```json
{
  "host": "127.0.0.1",
  "port": 8080
}
```

**配置优先级**：命令行参数 > 配置文件 > 默认值（`0.0.0.0:8000`）

#### 端口检测与自动分配

服务启动前自动检测指定端口是否可用：

- **端口正常**：直接启动服务，输出启动横幅
- **端口被占用 + 未指定 `--auto-port`**：打印错误提示及解决方案（含跨平台释放命令），以 exit code 1 退出
- **端口被占用 + 指定 `--auto-port`**：自动搜索 `port+1` 至 `port+100` 范围内的可用端口，找到后自动启动

错误提示示例：

```
============================================================
  [错误] 端口 8000 已被占用，无法启动服务！
============================================================
  [解决方案]
    方案一：指定其他端口
      python run.py --port 8001
    方案二：自动分配可用端口
      python run.py --port 8000 --auto-port
    方案三：查找并释放占用端口的进程
      netstat -ano | findstr :8000    # Windows
      taskkill /PID <进程ID> /F
      lsof -i :8000                    # Linux/macOS
      kill -9 <PID>
```

### 1.5 LLM 后端配置

`server_config.json` 支持通过 `llm` 节点配置 LLM 后端，切换不同的 API 提供商（如 DeepSeek 的 Anthropic 兼容 API），无需修改引擎代码。

#### 配置项说明

`llm` 节点支持 **`provider`** 字段，可选值为 `"anthropic"`（默认）或 `"openai"`。不同 provider 使用不同的环境变量映射：

```json
{
  "host": "0.0.0.0",
  "port": 8000,
  "llm": {
    "provider": "anthropic",
    "base_url": "",
    "api_key": "",
    "models": {
      "extract": "",
      "wiki": "",
      "reason": ""
    }
  }
}
```

##### Anthropic / DeepSeek 兼容模式（`provider: "anthropic"`）

| 配置路径 | 环境变量 | 默认值 | 说明 |
|----------|---------|--------|------|
| `llm.provider` | `LLM_PROVIDER` | `"anthropic"` | LLM 提供商类型 |
| `llm.base_url` | `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | API 端点地址 |
| `llm.api_key` | `ANTHROPIC_API_KEY` | 环境变量值 | API 密钥 |
| `llm.ssl_verify` | `OPENAI_SSL_VERIFY` | `true` | SSL 证书验证（仅 OpenAI 模式生效） |
| `llm.models.extract` | `VGD_EXTRACT_MODEL` | `claude-haiku-4-5` | 实体抽取与三元组提取的模型 |
| `llm.models.wiki` | `VGD_WIKI_MODEL` | `claude-haiku-4-5` | Wiki 创建与更新的模型 |
| `llm.models.reason` | `VGD_REASON_MODEL` | `claude-opus-4-7` | 综合推理问答的模型 |

##### OpenAI 模式（`provider: "openai"`）

```json
{
  "host": "0.0.0.0",
  "port": 8000,
  "llm": {
    "provider": "openai",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "sk-你的DeepSeek密钥",
    "ssl_verify": false,
    "models": {
      "extract": "deepseek-v4-flash",
      "wiki": "deepseek-v4-flash",
      "reason": "deepseek-v4-pro"
    }
  }
}
```

| 配置路径 | 环境变量 | 默认值 | 说明 |
|----------|---------|--------|------|
| `llm.provider` | `LLM_PROVIDER` | `"anthropic"` | 须设为 `"openai"` |
| `llm.base_url` | `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容 API 端点 |
| `llm.api_key` | `OPENAI_API_KEY` | 环境变量值 | API 密钥 |
| `llm.ssl_verify` | `OPENAI_SSL_VERIFY` | `true` | SSL 证书验证（企业网络代理需设为 `false`） |
| `llm.models.extract` | `VGD_EXTRACT_MODEL` | `claude-haiku-4-5` | 建议用 `deepseek-v4-flash` |
| `llm.models.wiki` | `VGD_WIKI_MODEL` | `claude-haiku-4-5` | 建议用 `deepseek-v4-flash` |
| `llm.models.reason` | `VGD_REASON_MODEL` | `claude-opus-4-7` | 建议用 `deepseek-v4-pro` |

**配置优先级**：配置文件 `llm` 节点 > 已设置的环境变量 > 引擎代码中的默认值。

> 留空的配置项不会覆盖已有的环境变量，仅非空值生效。例如 `"api_key": ""` 表示继续使用对应的环境变量（`ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY`）。

#### 典型场景：切换至 DeepSeek V4

1. 确认 `server_config.json` 中 `llm.provider` 为 `"anthropic"`（或留空）
2. 填入 DeepSeek 的 `base_url` 和 `api_key`，以及对应的模型名
3. 启动方式不变：

```bash
python run.py
```

启动日志中会输出 LLM 配置生效信息：

```
[配置] 已加载配置文件: server_config.json
[配置] LLM 提供商: anthropic
[配置] ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
[配置] ANTHROPIC_API_KEY=sk-5****e4
[配置] VGD_EXTRACT_MODEL=deepseek-v4-flash
[配置] VGD_WIKI_MODEL=deepseek-v4-flash
[配置] VGD_REASON_MODEL=deepseek-v4-pro
```

#### 典型场景：切换至 OpenAI

1. 在 `server_config.json` 中设置 `llm.provider` 为 `"openai"`
2. 填写 `base_url`、`api_key` 和建议的模型名
3. 启动方式不变：

```bash
python run.py
```

启动日志：

```
[配置] 已加载配置文件: server_config.json
[配置] LLM 提供商: openai
[配置] OPENAI_BASE_URL=https://api.openai.com/v1
[配置] OPENAI_API_KEY=sk-****abcd
[配置] VGD_EXTRACT_MODEL=gpt-4o-mini
[配置] VGD_WIKI_MODEL=gpt-4o-mini
[配置] VGD_REASON_MODEL=gpt-4o
```

#### 环境变量方式（备选）

也可完全通过环境变量配置，不修改配置文件：

```bash
# 切换至 DeepSeek（Windows）
set LLM_PROVIDER=anthropic
set ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
set ANTHROPIC_API_KEY=sk-你的DeepSeek密钥
set VGD_EXTRACT_MODEL=deepseek-v4-flash
set VGD_WIKI_MODEL=deepseek-v4-flash
set VGD_REASON_MODEL=deepseek-v4-pro
python run.py

# 切换至 OpenAI（Windows）
set LLM_PROVIDER=openai
set OPENAI_BASE_URL=https://api.openai.com/v1
set OPENAI_API_KEY=sk-你的OpenAI密钥
set VGD_EXTRACT_MODEL=gpt-4o-mini
set VGD_WIKI_MODEL=gpt-4o-mini
set VGD_REASON_MODEL=gpt-4o
python run.py

# Linux/macOS 将 set 换为 export 即可
```

#### 模型对照参考

| 角色 | Anthropic 模型 | DeepSeek V4 模型 | OpenAI 模型 | 说明 |
|------|---------------|-----------------|------------|------|
| 轻量抽取 | `claude-haiku-4-5` | `deepseek-v4-flash` | `gpt-4o-mini` | 实体识别、关系提取、Wiki 生成 |
| 深度推理 | `claude-opus-4-7` | `deepseek-v4-pro` | `gpt-4o` | 综合问答、跨实体推理 |

---

## 二、原理解析

### 2.1 设计哲学：为什么需要 Graph + Document 双脑？

人类记忆并非单一结构：

- 你记得「马斯克创立了 SpaceX」是一条**关系（图）**
- 你对「SpaceX 是一家什么公司」的理解是一段**叙事（文档）**

单纯用向量检索（RAG）只能召回相似片段，丢失结构；单纯用知识图谱只能查询关系，丢失语义细节。**VGD 的核心创新是让两者协同工作：**

| 维度 | Gbrain（图） | LLM-Wiki（文档） |
|------|-------------|----------------|
| 存储形态 | 三元组：`(Subject, Predicate, Object)` | Markdown：每个实体一页 |
| 擅长 | **多跳关系推理**（A→B→C→D） | **语义细节叙事**（人物背景、事件经过） |
| 写入方式 | 增量 upsert | Read-Reflect-Overwrite |
| 检索方式 | BFS 子图遍历 | 按实体 UUID 精确取页 |

### 2.2 核心工作流：「由图引路，由文生智」

这是 VGD 区别于普通 RAG 的关键流程，对应代码 `engines/orchestrator.py::query()`：

```
   ┌──────────────────────────────────────────────────────────┐
   │  Q: "Who founded OpenAI? Who invested in it?"            │
   └──────────────────────┬───────────────────────────────────┘
                          ▼
            ┌─────────────────────────┐
   Phase 1  │ 实体识别（NER）          │  ← Claude Haiku 4.5 / 字符串匹配
            │ ["OpenAI"]              │
            └─────────────┬───────────┘
                          ▼
            ┌─────────────────────────┐
   Phase 2  │ 由图引路：BFS 子图遍历   │  ← Gbrain
            │ OpenAI → Sam Altman     │
            │        → Elon Musk      │
            │        → Microsoft      │
            │        → ChatGPT        │
            │ depth=3                 │
            └─────────────┬───────────┘
                          ▼
            ┌─────────────────────────┐
   Phase 3  │ 由文生智：聚合 Wiki      │  ← LLM-Wiki
            │ for uuid in visited:    │
            │   wiki = get_wiki(uuid) │
            │ → 拼接 Markdown 上下文   │
            └─────────────┬───────────┘
                          ▼
            ┌─────────────────────────┐
   Phase 4  │ Claude Opus 4.7 综合作答 │  ← Adaptive Thinking
            │ + 推理过程展示           │  ← display: "summarized"
            └─────────────────────────┘
```

**关键设计点：**

1. **图先于文** —— 先用图找到「该看哪些实体」，避免 LLM 在海量 Wiki 中盲目检索
2. **文补于图** —— Wiki 提供图无法承载的语义密度（背景、动机、时间线）
3. **可控深度** —— 前端 `depth` 参数让用户决定语义跳跃距离
4. **可视化推理** —— `thinking={"type":"adaptive","display":"summarized"}` 把 Claude Opus 4.7 的思考过程也呈现出来

### 2.3 系统架构（六边形 / 端口适配器）

```
┌───────────────────────────────────────────────────────────────┐
│                          API 层                                │
│  FastAPI (api/app.py): /ingest, /query, /graph, /wiki/{uuid}  │
└──────────────────────────┬────────────────────────────────────┘
                           ▼
┌───────────────────────────────────────────────────────────────┐
│                        引擎层（核心业务）                       │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│   │  Gbrain      │  │  LLM-Wiki    │  │  Orchestrator    │   │
│   │  (NER/RE +   │  │  (R-R-O      │  │  (双脑协同 +     │   │
│   │   BFS)       │  │   Wiki)      │  │   Opus 推理)     │   │
│   └──────┬───────┘  └──────┬───────┘  └──────┬───────────┘   │
└──────────┼─────────────────┼─────────────────┼────────────────┘
           ▼                 ▼                 ▼
┌───────────────────────────────────────────────────────────────┐
│                    端口层（抽象接口）                          │
│   IGraphStoragePort  ←→  IDocumentStoragePort                 │
└──────────────────────────┬────────────────────────────────────┘
                           ▼
┌───────────────────────────────────────────────────────────────┐
│                    适配器层（可替换）                          │
│   InMemoryGraphAdapter      InMemoryDocumentAdapter           │
│   （生产环境可换为 Neo4j / PostgreSQL / S3 等）                │
└───────────────────────────────────────────────────────────────┘
```

**为什么用端口适配器？** 在 Demo 阶段我们用纯 Python dict 做内存存储，验证逻辑；生产环境只需实现新的 Adapter（比如 Neo4j Bolt 协议、PostgreSQL JSONB），引擎层和 API 层一行代码不用改。

---

## 三、目录结构

```
demo/
├── api/
│   └── app.py                  # FastAPI 后端，7 个 REST 端点
├── core/
│   ├── models.py               # GraphNode/Edge, DocumentDTO, TripleDTO 等 DTO
│   └── ports.py                # IGraphStoragePort, IDocumentStoragePort 接口
├── adapters/
│   └── memory_adapters.py      # 内存版 Graph/Document 实现
├── engines/
│   ├── gbrain.py               # 知识图谱引擎（NER+RE+BFS）
│   ├── llm_wiki.py             # 实体百科引擎（Read-Reflect-Overwrite）
│   ├── orchestrator.py         # 混合编排（由图引路 + 由文生智）
│   └── provider.py             # LLM 统一接入层（Anthropic / OpenAI）
├── static/
│   └── index.html              # 单页前端（D3.js + Marked.js）
├── docs/
│   ├── gbrain-technical.md     # Gbrain 技术穿刺
│   └── llm-wiki-technical.md   # LLM-Wiki 技术穿刺
├── requirements.txt
├── run.py                      # uvicorn 启动入口
└── README.md
```

---

## 四、API 速查

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/ingest` | 摄入文本 → 抽取三元组 + 写入图谱 + 生成/更新 Wiki |
| `POST` | `/api/query` | 混合检索问答（由图引路 + 由文生智） |
| `GET`  | `/api/graph` | 返回当前全图（节点 + 边）用于前端渲染 |
| `GET`  | `/api/wiki/{uuid}` | 获取某实体的 Wiki 页面 |
| `GET`  | `/api/nodes` | 列出所有节点 |
| `GET`  | `/api/stats` | 统计信息（节点数 / 边数 / Wiki 数 / 标签分布） |
| `DELETE` | `/api/edge` | 人工干预：标记一条边为过期 |

详细请求/响应示例见 `docs/gbrain-technical.md` 和 `docs/llm-wiki-technical.md`。

---

## 五、关键技术选型

| 组件 | 选择 | 理由 |
|------|------|------|
| LLM 接入层 | **Provider 抽象**（`engines/provider.py`） | 统一 Anthropic / OpenAI SDK 差异，切换后端零代码改动 |
| NER/RE 模型 | **Claude Haiku 4.5 / GPT-4o-mini** + `cache_control: ephemeral` | 长 system prompt 可缓存，每次调用低成本 |
| Wiki 写作模型 | **Claude Haiku 4.5 / GPT-4o-mini** | 结构化 Markdown 输出稳定 |
| 综合推理模型 | **Claude Opus 4.7 / GPT-4o** + `thinking: adaptive` | 跨实体关系推理需要深度思考 |
| 图遍历 | BFS（`collections.deque`） | 子图模式天然契合「多跳推理」需求 |
| 前端可视化 | **D3.js Force Layout** | 力导向布局直观展示实体聚类 |
| Markdown 渲染 | **Marked.js** | 浏览器内零依赖、纯前端渲染 Wiki |

---

## 六、扩展方向

- **持久化**：将 `InMemoryGraphAdapter` 替换为 Neo4j / Memgraph 实现；`InMemoryDocumentAdapter` 替换为 PostgreSQL + 全文索引
- **Vision 模态**：在 `core/ports.py` 中新增 `IVisionStoragePort`，引入 Claude 视觉理解，实现完整的 V-G-D 三脑
- **Embedding 路由**：当 NER 失败时回退到向量召回（pgvector / Qdrant），保证 Recall
- **冲突消解**：引入 `Read-Reflect-Overwrite` 的版本对比机制，在前端高亮哪些 Wiki 条目本次发生了变更
- **流式响应**：`/api/query` 改为 SSE，让 Claude Opus 4.7 的 thinking + answer 边产生边显示

---

## 七、相关文档

- 📘 [Gbrain 技术穿刺](docs/gbrain-technical.md) —— 数据如何进入图谱、引擎实时调用机制
- 📕 [LLM-Wiki 技术穿刺](docs/llm-wiki-technical.md) —— Wiki 如何生成与维护、Read-Reflect-Overwrite 详解
- 📗 上层架构原文请参考仓库根目录 `需求与系统架构设计说明书.md` 与 `深度技术架构与设计说明书.md`
