# VGD Memory OS — Graph-Document Hybrid Demo

> **由图引路，由文生智** · 一个面向 AI Agent 的混合记忆操作系统最小可运行原型

本 Demo 实现了 VGD（Vision–Gbrain–Document）记忆操作系统中的两大核心子系统 **Gbrain（左脑·知识图谱）** 与 **LLM-Wiki（右脑·实体百科）**，并通过一个 FastAPI 后端 + D3.js 前端把整条「文本摄入 → 记忆固化 → 混合检索 → 智能问答」链路完整跑通。

---

## 一、快速开始

### 1.1 环境要求

- Python ≥ 3.10
- 一个有效的 **Anthropic API Key**（设置为环境变量 `ANTHROPIC_API_KEY`）

### 1.2 安装与启动

```bash
cd demo
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-xxx        # Linux/macOS
# set ANTHROPIC_API_KEY=sk-ant-xxx         # Windows
python run.py
```

打开浏览器访问 `http://localhost:8000` 即可看到三栏式 Demo 界面。

### 1.3 三步体验

1. **摄入知识** Tab → 点击「加载示例数据」按钮 → 系统会自动注入一段科技公司场景文本
2. 等待几秒（Claude Haiku 4.5 抽取三元组 + 生成 Wiki），左侧图谱自动绘制
3. **智能问答** Tab → 输入「Who founded OpenAI? Who invested in it?」→ 观察图遍历高亮 + Claude Opus 4.7 综合作答

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
│   └── orchestrator.py         # 混合编排（由图引路 + 由文生智）
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
| NER/RE 模型 | **Claude Haiku 4.5** + `cache_control: ephemeral` | 长 system prompt 可缓存，每次调用仅 ~$0.001 |
| Wiki 写作模型 | **Claude Haiku 4.5** | 同上，结构化 Markdown 输出稳定 |
| 综合推理模型 | **Claude Opus 4.7** + `thinking: adaptive` + `effort: high` | 跨实体关系推理需要深度思考；adaptive 模式让 Claude 自主决定思考深度 |
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
