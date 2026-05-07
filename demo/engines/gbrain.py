import hashlib
import json
import re
from typing import Dict, List, Optional, Tuple

import anthropic

from core.models import GraphNode, TraversalResult, TripleDTO, make_uuid
from core.ports import IDocumentStoragePort, IGraphStoragePort

NER_SYSTEM_PROMPT = """You are an expert knowledge extraction system for a knowledge graph.
Extract named entities and their relationships from the given text.

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

Rules:
- subject and object must be specific named entities (not pronouns or generic terms)
- predicate should be a concise relationship (e.g., "founded", "works_at", "invested_in", "acquired", "located_in")
- Use exactly one of the labels: PERSON, COMPANY, EVENT, PROJECT, LOCATION, OTHER
- Extract 3-10 triples per text segment
- If no clear triples exist, return an empty array []
- Return ONLY the JSON array, no explanation"""


class GbrainEngine:
    def __init__(self, graph: IGraphStoragePort, docs: IDocumentStoragePort):
        self.graph = graph
        self.docs = docs
        self.client = anthropic.Anthropic()

    def extract_triples(self, text: str) -> List[TripleDTO]:
        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=2048,
                system=[
                    {
                        "type": "text",
                        "text": NER_SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": f"Extract knowledge triples from this text:\n\n{text}",
                    }
                ],
            )
            raw = response.content[0].text.strip()
            raw = re.sub(r"^```(?:json)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
            data = json.loads(raw)
            triples = []
            for item in data:
                triples.append(
                    TripleDTO(
                        subject=item.get("subject", ""),
                        subject_label=item.get("subject_label", "OTHER"),
                        predicate=item.get("predicate", "related_to"),
                        object=item.get("object", ""),
                        object_label=item.get("object_label", "OTHER"),
                    )
                )
            return triples
        except Exception as e:
            print(f"[GbrainEngine] extract_triples error: {e}")
            return []

    def _get_or_create_node(self, name: str, label: str) -> GraphNode:
        existing = self.graph.get_node_by_name(name)
        if existing:
            return existing
        uid = make_uuid()
        return self.graph.upsert_node(uid, label, name, {})

    def ingest_triples(self, triples: List[TripleDTO]) -> Dict:
        nodes_created = 0
        edges_created = 0
        for triple in triples:
            if not triple.subject or not triple.object:
                continue
            src_node = self._get_or_create_node(triple.subject, triple.subject_label)
            tgt_node = self._get_or_create_node(triple.object, triple.object_label)
            self.graph.upsert_edge(src_node.uuid, tgt_node.uuid, triple.predicate)
            nodes_created += 1
            edges_created += 1
        return {"nodes": nodes_created, "edges": edges_created}

    def find_start_nodes(self, entity_names: List[str]) -> List[str]:
        uuids = []
        for name in entity_names:
            node = self.graph.get_node_by_name(name)
            if node:
                uuids.append(node.uuid)
        if not uuids:
            all_nodes = self.graph.get_all_nodes()
            if all_nodes:
                uuids = [all_nodes[0].uuid]
        return uuids

    def traverse_from(self, start_uuids: List[str], max_depth: int = 3) -> Dict:
        merged_visited: Dict[str, int] = {}
        merged_path: List[str] = []
        merged_edges: List[Dict] = []
        seen_edges = set()

        for uid in start_uuids:
            result = self.graph.traverse_subgraph(uid, max_depth, {})
            for vuuid, depth in result.depth_map.items():
                if vuuid not in merged_visited:
                    merged_visited[vuuid] = depth
                    merged_path.append(vuuid)
            for edge in result.path_edges:
                eid = edge.get("id")
                if eid not in seen_edges:
                    seen_edges.add(eid)
                    merged_edges.append(edge)

        all_nodes = self.graph.get_all_nodes()
        node_map = {n.uuid: n.to_dict() for n in all_nodes}

        visited_nodes = []
        for uid in merged_visited:
            if uid in node_map:
                n = node_map[uid].copy()
                n["depth"] = merged_visited[uid]
                visited_nodes.append(n)

        return {
            "visited_uuids": list(merged_visited.keys()),
            "visited_nodes": visited_nodes,
            "traversal_path": merged_path,
            "path_edges": merged_edges,
        }
