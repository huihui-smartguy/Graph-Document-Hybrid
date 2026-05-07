# LLM-Wiki 技术穿刺文档

> 本文档面向后端开发者，详解 LLM-Wiki（实体百科引擎）的写作模式、Read-Reflect-Overwrite 算法和实时调用机制。

---

## 一、LLM-Wiki 在 VGD 中的定位

LLM-Wiki 是 VGD Memory OS 的「右脑」，与 Gbrain 形成互补：

- **Gbrain** 回答 "A 与 B 是什么关系"
- **LLM-Wiki** 回答 "A 是什么、它经历了什么、它为什么重要"

每个图谱中的实体在 LLM-Wiki 中对应**一篇结构化 Markdown 页面**，由 Claude Haiku 4.5 生成与维护。

代码位置：`engines/llm_wiki.py`

---

## 二、Wiki 页面规范

每篇 Wiki 严格遵循以下 Markdown 模板（由 `WIKI_CREATE_SYSTEM` 强制约束）：

```markdown
---
entity: OpenAI
label: COMPANY
updated: 2026-05-06
---

## Core Summary
[2-3 sentence overview]

## Key Facts
- [fact 1]
- [fact 2]

## Chronicle
[timeline of significant events]

## Relationships
[connections to other entities]

## Notes
[additional context]
```

**为什么固定结构？**

1. **可预测的 LLM 上下文** —— Orchestrator 把多篇 Wiki 拼接送入 Opus 时，结构一致便于模型快速定位字段
2. **便于增量更新** —— Read-Reflect-Overwrite 在更新时能精确合并到对应 section
3. **前端渲染友好** —— Marked.js 直接产出层次清晰的 HTML

---

## 三、数据导入：Wiki 何时被创建/更新

### 3.1 触发时机

Wiki 写入由 `HybridOrchestrator.ingest_text()` 在图谱写入完成**之后**统一触发：

```
用户 POST /api/ingest
    └─→ Orchestrator.ingest_text()
          ├─→ Gbrain.extract_triples()         ← 抽取三元组
          ├─→ Gbrain.ingest_triples()          ← 写入图谱（拿到 UUID）
          └─→ for each unique entity:
                LLMWikiEngine.get_or_create_wiki(...)   ← 写入 Wiki
```

**关键：** Wiki 写入的 `entity_uuid` 与图谱节点 UUID **完全一致**，这是双脑协同的桥梁——查询阶段从图谱拿到 UUID 列表，直接喂给 Wiki adapter 取页。

### 3.2 entity_facts 的聚合

Orchestrator 把同一实体在本次摄入中涉及的所有三元组聚合为「facts」，再喂给 LLM-Wiki：

```python
entity_facts = {}
for triple in triples:
    for entity_name, entity_label in [
        (triple.subject, triple.subject_label),
        (triple.object, triple.object_label),
    ]:
        node = self.gbrain.graph.get_node_by_name(entity_name)
        if node:
            if node.uuid not in entity_facts:
                entity_facts[node.uuid] = {
                    "name": entity_name,
                    "label": entity_label,
                    "facts": []
                }
            entity_facts[node.uuid]["facts"].append(
                f"{triple.subject} {triple.predicate} {triple.object}"
            )

for uuid, info in entity_facts.items():
    self.llm_wiki.get_or_create_wiki(
        entity_uuid=uuid,
        entity_name=info["name"],
        entity_label=info["label"],
        new_facts="\n".join(info["facts"]),
    )
```

**示例：** 对于实体 OpenAI，假如本次摄入产生了：

- `Sam Altman founded OpenAI`
- `Microsoft invested_in OpenAI`
- `OpenAI launched ChatGPT`

那么传给 `get_or_create_wiki` 的 `new_facts` 是一段三行文本，由 Claude Haiku 4.5 自由组织成结构化 Wiki。

---

## 四、Read-Reflect-Overwrite 模式详解

这是 LLM-Wiki 的**核心写作算法**，区别于普通 RAG「append-only」的关键。

### 4.1 三阶段流程

```
                ┌─────────────────────────────┐
   Read         │  从存储读取现有 Wiki         │
   读取          │  existing = docs.get_wiki()  │
                └────────────┬────────────────┘
                             ▼
                ┌─────────────────────────────┐
   Reflect      │  Claude Haiku 4.5 反思整合   │
   反思          │  - 保留正确信息              │
                │  - 整合新事实                │
                │  - 移除矛盾（新优先）        │
                └────────────┬────────────────┘
                             ▼
                ┌─────────────────────────────┐
   Overwrite    │  整体覆写新版本              │
   覆写          │  docs.save_wiki()           │
                │  + SHA256 版本哈希           │
                └─────────────────────────────┘
```

### 4.2 代码穿刺

**代码位置：** `engines/llm_wiki.py::get_or_create_wiki()`

```python
def get_or_create_wiki(self, entity_uuid, entity_name, entity_label, new_facts):
    existing = self.docs.get_wiki(entity_uuid)        # ← Read

    if existing is None:
        # 首次创建
        prompt = (
            f"Create a wiki page for this entity.\n\n"
            f"Entity Name: {entity_name}\n"
            f"Entity Type: {entity_label}\n\n"
            f"Known facts:\n{new_facts}"
        )
        response = self.client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            system=[{
                "type": "text",
                "text": WIKI_CREATE_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": prompt}],
        )
    else:
        # Read-Reflect-Overwrite
        prompt = (
            f"Current wiki page:\n\n{existing.content_markdown}\n\n"
            f"---\n\nNew information to integrate:\n{new_facts}"
        )
        response = self.client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            system=[{
                "type": "text",
                "text": WIKI_UPDATE_SYSTEM,                ## ← Reflect prompt
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": prompt}],
        )

    content = response.content[0].text.strip()
    version_hash = self._hash(content)                     # ← 16 位 SHA256
    self.docs.save_wiki(entity_uuid, entity_name, content, version_hash)  # ← Overwrite
    return self.docs.get_wiki(entity_uuid)
```

### 4.3 Update System Prompt 解析

```
You are a knowledge base editor applying the Read-Reflect-Overwrite pattern.

Given an existing wiki page and new information, produce an updated wiki page that:
1. Preserves all existing accurate information           ← 保
2. Integrates new facts naturally                        ← 增
3. Removes any contradictions (new info takes precedence)  ← 改
4. Maintains the same Markdown structure                 ← 一致性

Return ONLY the complete updated wiki page content, no explanation.
```

**核心原则：** 新信息**不是简单追加**，而是由 LLM 进行**语义级合并**——这是 R-R-O 区别于传统 append-only 笔记的关键。例如旧 Wiki 写「OpenAI 是非营利组织」，新事实「OpenAI 转为有限盈利公司」，R-R-O 会把旧句子重写为「OpenAI 最初为非营利组织，后转为有限盈利公司」。

### 4.4 版本哈希

```python
def _hash(self, content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]
```

每次 Overwrite 生成一个 16 位 SHA256 截断哈希，用途：

- 前端 Wiki 页面右上角显示 `v3a8c2b1...`，让用户感知版本变化
- 未来可基于此实现 diff 视图、回滚机制

---

## 五、查询阶段：实时调用 LLM-Wiki

### 5.1 入口与调用栈

```
POST /api/query
    └─→ Orchestrator.query()
          ├─→ Gbrain.traverse_from()  ← 拿到 visited_uuids
          ├─→ LLMWikiEngine.get_multi_wiki_context(visited_uuids)
          └─→ Claude Opus 4.7 综合作答
```

### 5.2 多页 Wiki 聚合

**代码位置：** `engines/llm_wiki.py::get_multi_wiki_context()`

```python
def get_multi_wiki_context(self, entity_uuids: List[str], max_entities: int = 6) -> str:
    sections = []
    for uid in entity_uuids[:max_entities]:           # ← 限流，最多 6 个
        doc = self.docs.get_wiki(uid)
        if doc:
            sections.append(f"### Wiki: {doc.entity_name}\n\n{doc.content_markdown}")
    if not sections:
        return "No wiki pages available yet."
    return "\n\n---\n\n".join(sections)
```

**为什么限流到 6 个？**

- Claude Opus 4.7 上下文窗口很大（1M），但**质量与数量不成正比**
- BFS 通常按 depth 排序，前 6 个是与问题最相关的核心实体
- 控制总输入 token 量，让 Opus 把推理预算花在「关系串联」而非「读完所有 Wiki」

### 5.3 与图上下文的拼接

`Orchestrator.query()` 把 Gbrain 的图描述与 LLM-Wiki 的多页内容拼接为 Opus 的最终输入：

```python
combined_context = (
    f"{graph_context}\n\n"
    f"---\n\n"
    f"**Wiki Knowledge Base:**\n\n{wiki_context}"
)

response = self.client.messages.create(
    model="claude-opus-4-7",
    max_tokens=4096,
    thinking={"type": "adaptive", "display": "summarized"},
    output_config={"effort": "high"},
    system=HYBRID_QUERY_SYSTEM,
    messages=[{
        "role": "user",
        "content": f"Question: {question}\n\n{combined_context}",
    }],
)
```

**Adaptive Thinking + display=summarized：** Claude Opus 4.7 自主决定思考深度，并把推理过程的摘要返回——前端在「Claude 推理过程」面板展示，让用户看到「为什么这样作答」。

---

## 六、单页 Wiki 直查 API

除了在问答中被聚合调用，前端还可以单独请求某实体的 Wiki：

### 6.1 `GET /api/wiki/{uuid}`

```http
GET /api/wiki/f3a8c2b1...
```

**响应体：**
```json
{
  "entity_uuid": "f3a8c2b1...",
  "entity_name": "OpenAI",
  "content_markdown": "---\nentity: OpenAI\n...",
  "version_hash": "3a8c2b1d4e5f6789",
  "updated_at": 1715000000.0
}
```

### 6.2 触发场景

- 前端「实体百科」Tab 点击 entity-chip
- D3 力导向图中点击节点
- API 二次开发：构建实体详情页

代码位置：`api/app.py::get_wiki()`

---

## 七、关键技术权衡

### 7.1 为什么用 Claude Haiku 4.5 而不是 Opus？

| 维度 | Haiku 4.5 | Opus 4.7 |
|------|-----------|----------|
| 成本 | $1 / $5 per 1M | $5 / $25 per 1M |
| 延迟 | ~500ms | ~3-8s |
| 适合任务 | 结构化输出、模板填充 | 跨实体推理、深度综合 |

Wiki 生成是**模板填充类任务**，Haiku 完全胜任；Opus 留给真正需要「跨多篇 Wiki + 图关系综合推理」的查询阶段。

### 7.2 为什么 Read-Reflect-Overwrite 而不是增量 Patch？

- **Patch 模式**（如 git diff）：精确但脆弱——LLM 输出 diff 时极易出错（行号偏移、上下文不匹配）
- **R-R-O 模式**：让 LLM 整体重写，容错率高，且能借机消解矛盾

代价是每次更新都要重写整页（~1k token），但 Haiku 成本极低，可承受。

### 7.3 为什么每次都触发 Prompt Caching？

`WIKI_CREATE_SYSTEM` 和 `WIKI_UPDATE_SYSTEM` 都加了 `cache_control: ephemeral`：

- 长 system prompt（~400 token）首次写入缓存
- 后续 5 分钟内调用命中缓存，输入成本降到 1/10
- 在批量摄入（一次 ingest 触发多个 Wiki 写入）时收益尤其明显

---

## 八、生产环境演进路径

| 关注点 | 当前 Demo | 生产建议 |
|--------|----------|---------|
| 存储 | 内存 dict | PostgreSQL JSONB / S3 + Postgres 索引 |
| 版本管理 | 16 位哈希覆写 | Git-style 版本树，支持 diff/rollback |
| 并发写入 | 无锁 | 实体级 mutex 或乐观锁（version 字段） |
| 缓存命中率监控 | 无 | 上报 `usage.cache_read_input_tokens` 到 Prometheus |
| 大规模 Wiki | 全量重写 | 分块（per section）写作 + 选择性更新 |
| 多语言 | 单语 | 在 system prompt 中加入 `language: zh-CN` 控制 |

替换存储时只需新写一个 `IDocumentStoragePort` 实现：

```python
class PostgresDocumentAdapter(IDocumentStoragePort):
    def save_wiki(self, entity_uuid, entity_name, content_markdown, version_hash) -> bool:
        ...
    def get_wiki(self, entity_uuid) -> Optional[DocumentDTO]:
        ...
    def get_all_wikis(self) -> List[DocumentDTO]:
        ...
```

`api/app.py` 启动时把 `InMemoryDocumentAdapter` 换成它即可，引擎层完全无感知。

---

## 九、调试技巧

### 9.1 直接在 REPL 玩 LLM-Wiki

```python
from adapters.memory_adapters import InMemoryDocumentAdapter
from engines.llm_wiki import LLMWikiEngine

d = InMemoryDocumentAdapter()
w = LLMWikiEngine(d)

# 首次创建
doc = w.get_or_create_wiki(
    entity_uuid="test-uuid-1",
    entity_name="OpenAI",
    entity_label="COMPANY",
    new_facts="Sam Altman founded OpenAI in 2015.\nMicrosoft invested $13B in OpenAI.",
)
print(doc.content_markdown)
print("v" + doc.version_hash)

# 触发 R-R-O 更新
doc2 = w.get_or_create_wiki(
    entity_uuid="test-uuid-1",
    entity_name="OpenAI",
    entity_label="COMPANY",
    new_facts="OpenAI launched ChatGPT in November 2022.",
)
print(doc2.content_markdown)         # 应包含原有内容 + 新增 ChatGPT 段
print("v" + doc2.version_hash)       # 哈希应改变
```

### 9.2 验证 Wiki 与图谱的 UUID 一致性

```python
node = graph.get_node_by_name("OpenAI")
wiki = docs.get_wiki(node.uuid)
assert wiki is not None and wiki.entity_name == "OpenAI"
```

### 9.3 观察 R-R-O 的 token 消耗

```python
print(response.usage.input_tokens)        # 现有 Wiki + 新事实
print(response.usage.output_tokens)       # 重写后的整页
print(response.usage.cache_read_input_tokens)   # 命中的 system prompt
```

---

## 十、与上层架构文档的对应关系

| 本文档章节 | 仓库根 `深度技术架构与设计说明书.md` 章节 |
|-----------|---------------------------------------|
| §2 Wiki 页面规范 | "LLM-Wiki · SSOT 与结构化页面" |
| §4 Read-Reflect-Overwrite | "LLM-Wiki · 写作模式 · R-R-O 范式" |
| §5.2 多页聚合 | "VGD 整体 · 由文生智 · 上下文构造" |
| §7.2 R-R-O vs Patch | "LLM-Wiki · 设计权衡" |
