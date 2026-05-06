from contextlib import asynccontextmanager
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from adapters.memory_adapters import InMemoryDocumentAdapter, InMemoryGraphAdapter
from engines.gbrain import GbrainEngine
from engines.llm_wiki import LLMWikiEngine
from engines.orchestrator import HybridOrchestrator


graph_adapter = InMemoryGraphAdapter()
doc_adapter = InMemoryDocumentAdapter()
gbrain = GbrainEngine(graph_adapter, doc_adapter)
llm_wiki = LLMWikiEngine(doc_adapter)
orchestrator = HybridOrchestrator(gbrain, llm_wiki)


app = FastAPI(title="VGD Memory OS Demo", version="1.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")


class IngestRequest(BaseModel):
    text: str


class QueryRequest(BaseModel):
    question: str
    max_depth: int = 3


class DeleteEdgeRequest(BaseModel):
    src_uuid: str
    tgt_uuid: str


@app.get("/", response_class=HTMLResponse)
async def index():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()


@app.post("/api/ingest")
async def ingest(req: IngestRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    stats = orchestrator.ingest_text(req.text)
    return {"status": "ok", "stats": stats}


@app.post("/api/query")
async def query(req: QueryRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    result = orchestrator.query(req.question, max_depth=req.max_depth)
    return {"status": "ok", "result": result}


@app.get("/api/graph")
async def get_graph():
    nodes = [n.to_dict() for n in graph_adapter.get_all_nodes()]
    edges = [e.to_dict() for e in graph_adapter.get_all_edges()]
    return {"nodes": nodes, "edges": edges}


@app.get("/api/wiki/{uuid}")
async def get_wiki(uuid: str):
    doc = doc_adapter.get_wiki(uuid)
    if not doc:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    return {
        "entity_uuid": doc.entity_uuid,
        "entity_name": doc.entity_name,
        "content_markdown": doc.content_markdown,
        "version_hash": doc.version_hash,
        "updated_at": doc.updated_at,
    }


@app.get("/api/nodes")
async def list_nodes():
    nodes = [n.to_dict() for n in graph_adapter.get_all_nodes()]
    return {"nodes": nodes, "count": len(nodes)}


@app.delete("/api/edge")
async def delete_edge(req: DeleteEdgeRequest):
    success = graph_adapter.human_override_delete_edge(req.src_uuid, req.tgt_uuid)
    if not success:
        raise HTTPException(status_code=404, detail="Edge not found")
    return {"status": "ok", "message": "Edge marked as expired (human override)"}


@app.get("/api/stats")
async def stats():
    all_nodes = graph_adapter.get_all_nodes()
    all_edges = graph_adapter.get_all_edges()
    all_wikis = doc_adapter.get_all_wikis()
    label_counts: Dict[str, int] = {}
    for node in all_nodes:
        label_counts[node.label] = label_counts.get(node.label, 0) + 1
    return {
        "total_nodes": len(all_nodes),
        "total_edges": len(all_edges),
        "total_wikis": len(all_wikis),
        "label_distribution": label_counts,
    }
