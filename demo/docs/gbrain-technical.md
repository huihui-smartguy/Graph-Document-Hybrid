# Gbrain 技术穿刺文档

> 本文档面向后端开发者，逐行解析 Gbrain（知识图谱引擎）的数据流、调用栈和实时记忆构建机制。

---

## 一、Gbrain 在 VGD 中的定位

Gbrain 是 VGD Memory OS 的「左脑」，负责把**非结构化文本**转化为**结构化的实体–关系图**。其核心职责：

1. **NER + RE 联合抽取**：从自然语言中识别实体并抽取关系三元组
2. **图谱构建与维护**：增量 upsert 节点和边，保持名称索引一致性
3. **多跳子图遍历**：在查询阶段为下游 Wiki 检索提供「该看哪些实体」的导航

代码位置：`engines/gbrain.py`

---

## 二、数据导入完整链路

### 2.1 入口：`POST /api/ingest`

前端「摄入知识」Tab 把文本通过 JSON 提交：

```http
POST /api/ingest
Content-Type: application/json

{ "text": "Sam Altman is the CEO of OpenAI..." }
```

### 2.2 调用栈

```
api/app.py::ingest()
    └─→ HybridOrchestrator.ingest_text(text)
            ├─→ GbrainEngine.extract_triples(text)         ← 步骤 1：NER+RE
            ├─→ GbrainEngine.ingest_triples(triples)       ← 步骤 2：upsert 图谱
            └─→ LLMWikiEngine.get_or_create_wiki(...)      ← 步骤 3：实体百科
```

下面逐步穿刺。

---

### 2.3 步骤 1：NER + RE 抽取

**代码位置：** `engines/gbrain.py::extract_triples()`

```python
response = self.client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=2048,
    system=[{
        "type": "text",
        "text": NER_SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},   # ← 关键：prompt caching
    }],
    messages=[{
        "role": "user",
        "content": f"Extract knowledge triples from this text:\n\n{text}",
    }],
)
```

**关键设计：**

1. **使用 Claude Haiku 4.5**：抽取任务结构化、上下文短，Haiku 的 latency（~500ms）和成本（$1/$5 per 1M）非常合适
2. **Prompt Caching**：`NER_SYSTEM_PROMPT` 长度约 800 token，加 `cache_control: ephemeral` 后，从第二次调用起命中缓存，单次成本降到 ~$0.0005
3. **强制 JSON 输出**：System prompt 明确要求「Return ONLY a valid JSON array」，避免回退到自然语言解析

**System Prompt 核心约束：**

```
Return ONLY a valid JSON array of triple objects with this exact structure:
[
  {
    "subject": "entity name",
    "subject_label": "PERSON|COMPANY|EVENT|PROJECT|LOCATION|OTHER",
    "predicate": "relationship verb phrase",
    "object": "entity name",
    "object_label": "PERSON|COMPANY|EVENT|PROJECT|LOCATION|OTHER"
  }
]
```

**输出解析（容错处理）：**

```python
raw = response.content[0].text.strip()
raw = re.sub(r"^```(?:json)?\n?", "", raw)   # 剥离可能的 markdown 包装
raw = re.sub(r"\n?```$", "", raw)
data = json.loads(raw)
```

**失败兜底：** 任何异常（API 错误、JSON 解析失败）都返回空数组 `[]`，保证主流程不中断。

---

### 2.4 步骤 2：三元组写入图谱

**代码位置：** `engines/gbrain.py::ingest_triples()`

```python
def ingest_triples(self, triples: List[TripleDTO]) -> Dict:
    for triple in triples:
        if not triple.subject or not triple.object:
            continue
        src_node = self._get_or_create_node(triple.subject, triple.subject_label)
        tgt_node = self._get_or_create_node(triple.object, triple.object_label)
        self.graph.upsert_edge(src_node.uuid, tgt_node.uuid, triple.predicate)
```

**节点 upsert 逻辑（`_get_or_create_node`）：**

1. 用 `name.lower()` 在 `name_index` 中查找
2. 命中则返回已有节点（保留原 UUID，确保 Wiki 引用稳定）
3. 未命中则生成新 UUID，写入 `nodes` 和 `name_index`

```python
def _get_or_create_node(self, name: str, label: str) -> GraphNode:
    existing = self.graph.get_node_by_name(name)
    if existing:
        return existing
    uid = make_uuid()
    return self.graph.upsert_node(uid, label, name, {})
```

**边 upsert 逻辑（`InMemoryGraphAdapter.upsert_edge`）：**

```python
for edge in self.edges:
    if edge.src_uuid == src_uuid and edge.tgt_uuid == tgt_uuid \
       and edge.relation == relation:
        edge.weight = max(edge.weight, weight)
        edge.expired = False                 # 复活被人工标记过期的边
        return edge
# 否则新建
edge = GraphEdge(id=make_uuid(), ...)
self.edges.append(edge)
```

**幂等性保证：** 同一文本重复摄入不会产生重复节点和边，只会刷新 weight 和 expired 状态。

---

### 2.5 步骤 3：Wiki 写入（跨引擎协作）

`HybridOrchestrator.ingest_text()` 在图谱写入完成后，**对每个唯一实体** 触发 Wiki 生成：

```python
entity_facts: Dict[str, Dict] = {}
for triple in triples:
    for entity_name, entity_label in [
        (triple.subject, triple.subject_label),
        (triple.object, triple.object_label),
    ]:
        node = self.gbrain.graph.get_node_by_name(entity_name)
        if node:
            if node.uuid not in entity_facts:
                entity_facts[node.uuid] = {"name": ..., "label": ..., "facts": []}
            entity_facts[node.uuid]["facts"].append(
                f"{triple.subject} {triple.predicate} {triple.object}"
            )

for entity_uuid, info in entity_facts.items():
    self.llm_wiki.get_or_create_wiki(
        entity_uuid=entity_uuid,
        entity_name=info["name"],
        entity_label=info["label"],
        new_facts="\n".join(info["facts"]),
    )
```

**关键点：** Wiki 的写入不是直接由 Gbrain 触发，而是 Orchestrator 协调——Gbrain 只负责「生成 UUID 和图结构」，Wiki 生成委托给 LLMWikiEngine（详见 [llm-wiki-technical.md](llm-wiki-technical.md)）。

---

### 2.6 摄入后端响应示例

```json
{
  "status": "ok",
  "stats": {
    "triples": 12,
    "nodes": 12,
    "edges": 12,
    "wikis_updated": 9
  }
}
```

注：`nodes` 和 `edges` 计数包含重复（已 upsert 但未新建），`wikis_updated` 为唯一实体数。

---

## 三、查询阶段：实时调用 Gbrain

### 3.1 入口：`POST /api/query`

```http
POST /api/query
Content-Type: application/json

{ "question": "Who founded OpenAI?", "max_depth": 3 }
```

### 3.2 调用栈

```
api/app.py::query()
    └─→ HybridOrchestrator.query(question, max_depth)
            ├─→ HybridOrchestrator._extract_entities_from_query()  ← 实体识别
            ├─→ GbrainEngine.find_start_nodes(entity_names)        ← 起点定位
            ├─→ GbrainEngine.traverse_from(start_uuids, max_depth) ← BFS 遍历
            ├─→ HybridOrchestrator._build_graph_context(traversal) ← 图上下文
            ├─→ LLMWikiEngine.get_multi_wiki_context(...)          ← 文上下文
            └─→ Claude Opus 4.7 综合作答
```

### 3.3 实体识别（双轨策略）

`HybridOrchestrator._extract_entities_from_query()`：

```python
# 轨道 1：字符串匹配（零成本，毫秒级）
known_names = [n.name for n in all_nodes]
matched = [name for name in known_names if name.lower() in question.lower()]
if matched:
    return matched

# 轨道 2：Claude Haiku 4.5 兜底（处理同义词、缩写）
response = self.client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=256,
    system=ENTITY_EXTRACT_SYSTEM,
    messages=[{"role": "user", "content": question}],
)
```

**为什么双轨？** 90% 的情况下用户问题中直接出现实体名（如 "OpenAI"），字符串匹配即可命中，零 API 成本；只在显式名缺失时才调用 LLM。

### 3.4 BFS 多跳遍历

**代码位置：** `adapters/memory_adapters.py::traverse_subgraph()`

```python
def traverse_subgraph(self, start_uuid: str, max_depth: int, filters: dict):
    visited: Dict[str, int] = {}      # uuid -> depth
    queue = deque([(start_uuid, 0)])
    path_edges = []

    while queue:
        current_uuid, depth = queue.popleft()
        if current_uuid in visited:
            continue
        visited[current_uuid] = depth
        if depth >= max_depth:
            continue
        for edge in self.edges:
            if edge.expired:                    # 跳过人工标记过期的边
                continue
            next_uuid = (
                edge.tgt_uuid if edge.src_uuid == current_uuid
                else edge.src_uuid if edge.tgt_uuid == current_uuid
                else None
            )
            if next_uuid and next_uuid not in visited:
                path_edges.append(edge.to_dict())
                queue.append((next_uuid, depth + 1))

    return TraversalResult(...)
```

**关键设计：**

- **无向遍历**：边在 BFS 中双向可达（`src→tgt` 和 `tgt→src` 都能跳），符合人类联想记忆
- **expired 过滤**：人工通过 `DELETE /api/edge` 标记的边不参与遍历，但仍保留历史记录
- **depth_map**：记录每个节点的最浅深度，用于前端按深度高亮

### 3.5 多起点合并（`traverse_from`）

当问题包含多个实体时（如 "OpenAI 和 Tesla 的关系？"），需要从多个起点同时 BFS 并合并子图：

```python
def traverse_from(self, start_uuids: List[str], max_depth: int):
    merged_visited: Dict[str, int] = {}
    seen_edges = set()
    for uid in start_uuids:
        result = self.graph.traverse_subgraph(uid, max_depth, {})
        for vuuid, depth in result.depth_map.items():
            if vuuid not in merged_visited:
                merged_visited[vuuid] = depth     # 保留最浅深度
        for edge in result.path_edges:
            if edge["id"] not in seen_edges:
                seen_edges.add(edge["id"])
                merged_edges.append(edge)
    ...
```

### 3.6 图上下文构建

`HybridOrchestrator._build_graph_context()` 把 BFS 结果格式化为 LLM 友好的文本：

```
**Graph Traversal Results:**

Discovered 8 entities via BFS traversal:

- [PERSON] **Sam Altman** (depth=1)
- [COMPANY] **OpenAI** (depth=0)
- [PERSON] **Elon Musk** (depth=1)
- [COMPANY] **Microsoft** (depth=1)
- [PROJECT] **ChatGPT** (depth=2)
...

Key relationships (15 shown):
- Sam Altman --[founded]--> OpenAI
- Elon Musk --[founded]--> OpenAI
- Microsoft --[invested_in]--> OpenAI
...
```

这段文本随后与 Wiki 上下文一起送入 Claude Opus 4.7。

---

## 四、实时性与并发模型

### 4.1 当前实现：单进程 + 全局单例

`api/app.py` 启动时创建全局单例：

```python
graph_adapter = InMemoryGraphAdapter()
doc_adapter = InMemoryDocumentAdapter()
gbrain = GbrainEngine(graph_adapter, doc_adapter)
```

所有请求共享一份内存图谱。这意味着：

- **优点**：零持久化开销，毫秒级图遍历
- **限制**：进程重启数据全失；多 worker 模式下数据隔离

### 4.2 生产环境演进路径

| 关注点 | 当前 Demo | 生产建议 |
|--------|----------|---------|
| 持久化 | 内存 dict | Neo4j / Memgraph / Postgres + AGE |
| 并发安全 | 无锁（单进程） | Adapter 内加 `asyncio.Lock` 或委托 DB 事务 |
| 大规模图 | O(E) 全表扫边 | Adapter 改为邻接表 / 索引 |
| NER 吞吐 | 同步串行 | Anthropic Batch API（成本减半） |

替换适配器时，**只需新写一个实现 `IGraphStoragePort` 的类**，引擎层完全无感知。

---

## 五、关键 API 数据契约

### 5.1 `POST /api/ingest`

**请求体：**
```json
{ "text": "..." }
```

**响应体：**
```json
{
  "status": "ok",
  "stats": {
    "triples": 12,           // 抽取出的三元组数量
    "nodes": 12,             // 涉及的节点写入次数（含 upsert）
    "edges": 12,             // 边写入次数
    "wikis_updated": 9       // 触发 Wiki 写入的唯一实体数
  }
}
```

### 5.2 `GET /api/graph`

**响应体：**
```json
{
  "nodes": [
    {
      "uuid": "f3a...",
      "label": "PERSON",
      "name": "Sam Altman",
      "properties": {},
      "created_at": 1715000000.0
    }
  ],
  "edges": [
    {
      "id": "a8b...",
      "src_uuid": "f3a...",
      "tgt_uuid": "c2d...",
      "relation": "founded",
      "weight": 1.0,
      "expired": false
    }
  ]
}
```

### 5.3 `DELETE /api/edge`

**请求体：**
```json
{ "src_uuid": "f3a...", "tgt_uuid": "c2d..." }
```

把指定方向的所有边标记为 `expired=True`，BFS 遍历时跳过。**不真正删除**，保留审计痕迹。

---

## 六、调试技巧

### 6.1 在 Python REPL 直接玩 Gbrain

```python
from adapters.memory_adapters import InMemoryGraphAdapter, InMemoryDocumentAdapter
from engines.gbrain import GbrainEngine

g = InMemoryGraphAdapter()
d = InMemoryDocumentAdapter()
gb = GbrainEngine(g, d)

triples = gb.extract_triples("Elon Musk founded SpaceX in 2002.")
print(triples)
gb.ingest_triples(triples)
print(g.get_all_nodes())
```

### 6.2 观察 BFS 遍历

```python
node = g.get_node_by_name("SpaceX")
result = g.traverse_subgraph(node.uuid, max_depth=2, filters={})
print(result.depth_map)        # {uuid: depth}
print(result.path_edges)       # 走过的边
```

### 6.3 验证 Prompt Caching 命中

每次调用 `extract_triples` 后查看 `response.usage`：

```python
print(response.usage.cache_read_input_tokens)   # > 0 表示命中缓存
print(response.usage.cache_creation_input_tokens)
```

---

## 七、与上层架构文档的对应关系

| 本文档章节 | 仓库根 `深度技术架构与设计说明书.md` 章节 |
|-----------|---------------------------------------|
| §2.3 步骤 1 NER+RE | "Gbrain · 第一性原理 · 实体–关系联合抽取" |
| §2.4 三元组写入 | "Gbrain · 写路径 · upsert 语义" |
| §3.4 BFS 多跳遍历 | "Gbrain · 读路径 · 子图遍历" |
| §4 端口适配器 | "VGD 整体 · 六边形架构" |
