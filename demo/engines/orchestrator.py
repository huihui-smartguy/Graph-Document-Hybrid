import re
from typing import Dict, List, Optional

import anthropic

from core.ports import IDocumentStoragePort, IGraphStoragePort
from engines.gbrain import GbrainEngine
from engines.llm_wiki import LLMWikiEngine

HYBRID_QUERY_SYSTEM = """You are an intelligent knowledge synthesis engine powered by the VGD Memory OS (Vision-Gbrain-Document).

You have access to two complementary knowledge sources:
1. **Graph Context (Gbrain)**: Structured entity relationships discovered through multi-hop BFS traversal
2. **Wiki Context (LLM-Wiki)**: Rich, detailed Markdown pages for each entity

Your task is to synthesize both sources to answer the user's question accurately and insightfully.

Guidelines:
- Lead with the most directly relevant information
- Connect entities through their graph relationships
- Use wiki details to enrich and contextualize the answer
- If information is incomplete, acknowledge it honestly
- Format your response in clear Markdown with relevant headers
- Conclude with a brief insight about key entity relationships discovered"""

ENTITY_EXTRACT_SYSTEM = """Extract entity names from the user's question for knowledge graph lookup.
Return ONLY a JSON array of strings — the entity names to look up.
Example: ["Elon Musk", "Tesla", "SpaceX"]
If no specific entities, return []"""


class HybridOrchestrator:
    def __init__(self, gbrain: GbrainEngine, llm_wiki: LLMWikiEngine):
        self.gbrain = gbrain
        self.llm_wiki = llm_wiki
        self.client = anthropic.Anthropic()

    def _extract_entities_from_query(self, question: str) -> List[str]:
        all_nodes = self.gbrain.graph.get_all_nodes()
        if not all_nodes:
            return []

        known_names = [n.name for n in all_nodes]
        matched = []
        q_lower = question.lower()
        for name in known_names:
            if name.lower() in q_lower:
                matched.append(name)
        if matched:
            return matched

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=256,
                system=ENTITY_EXTRACT_SYSTEM,
                messages=[{"role": "user", "content": question}],
            )
            import json
            raw = response.content[0].text.strip()
            raw = re.sub(r"^```(?:json)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
            return json.loads(raw)
        except Exception:
            return []

    def _build_graph_context(self, traversal: Dict) -> str:
        nodes = traversal.get("visited_nodes", [])
        edges = traversal.get("path_edges", [])

        if not nodes:
            return "No graph context available."

        all_graph_nodes = self.gbrain.graph.get_all_nodes()
        node_name_map = {n.uuid: n.name for n in all_graph_nodes}

        lines = ["**Graph Traversal Results:**\n"]
        lines.append(f"Discovered {len(nodes)} entities via BFS traversal:\n")
        for node in nodes[:10]:
            depth = node.get("depth", 0)
            lines.append(f"- [{node['label']}] **{node['name']}** (depth={depth})")

        if edges:
            lines.append(f"\nKey relationships ({min(len(edges), 15)} shown):")
            for edge in edges[:15]:
                src_name = node_name_map.get(edge["src_uuid"], edge["src_uuid"][:8])
                tgt_name = node_name_map.get(edge["tgt_uuid"], edge["tgt_uuid"][:8])
                lines.append(f"- {src_name} --[{edge['relation']}]--> {tgt_name}")

        return "\n".join(lines)

    def ingest_text(self, text: str) -> Dict:
        triples = self.gbrain.extract_triples(text)
        if not triples:
            return {"triples": 0, "nodes": 0, "edges": 0, "wikis_updated": 0}

        stats = self.gbrain.ingest_triples(triples)

        entity_facts: Dict[str, List[str]] = {}
        for triple in triples:
            for entity_name, entity_label in [
                (triple.subject, triple.subject_label),
                (triple.object, triple.object_label),
            ]:
                if not entity_name:
                    continue
                node = self.gbrain.graph.get_node_by_name(entity_name)
                if node:
                    if node.uuid not in entity_facts:
                        entity_facts[node.uuid] = {"name": entity_name, "label": entity_label, "facts": []}
                    entity_facts[node.uuid]["facts"].append(
                        f"{triple.subject} {triple.predicate} {triple.object}"
                    )

        wikis_updated = 0
        for entity_uuid, info in entity_facts.items():
            facts_text = "\n".join(info["facts"])
            self.llm_wiki.get_or_create_wiki(
                entity_uuid=entity_uuid,
                entity_name=info["name"],
                entity_label=info["label"],
                new_facts=facts_text,
            )
            wikis_updated += 1

        return {
            "triples": len(triples),
            "nodes": stats["nodes"],
            "edges": stats["edges"],
            "wikis_updated": wikis_updated,
        }

    def query(self, question: str, max_depth: int = 3) -> Dict:
        entity_names = self._extract_entities_from_query(question)
        start_uuids = self.gbrain.find_start_nodes(entity_names)

        if not start_uuids:
            return {
                "answer": "No entities found in the knowledge graph matching your question. Please ingest some text first.",
                "thinking": "",
                "traversal": {},
                "graph_context": "",
                "wiki_context": "",
            }

        traversal = self.gbrain.traverse_from(start_uuids, max_depth)
        graph_context = self._build_graph_context(traversal)
        wiki_context = self.llm_wiki.get_multi_wiki_context(traversal["visited_uuids"])

        combined_context = f"{graph_context}\n\n---\n\n**Wiki Knowledge Base:**\n\n{wiki_context}"

        response = self.client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": "high"},
            system=HYBRID_QUERY_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": f"Question: {question}\n\n{combined_context}",
                }
            ],
        )

        thinking_text = ""
        answer_text = ""
        for block in response.content:
            if block.type == "thinking":
                thinking_text = getattr(block, "summary", "") or getattr(block, "thinking", "")
            elif block.type == "text":
                answer_text = block.text

        return {
            "answer": answer_text,
            "thinking": thinking_text,
            "traversal": traversal,
            "graph_context": graph_context,
            "wiki_context": wiki_context,
            "entities_found": entity_names,
            "nodes_visited": len(traversal.get("visited_uuids", [])),
        }
