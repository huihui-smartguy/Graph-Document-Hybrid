from collections import deque
from typing import Dict, List, Optional

from core.models import DocumentDTO, GraphEdge, GraphNode, TraversalResult, make_uuid
from core.ports import IDocumentStoragePort, IGraphStoragePort


class InMemoryGraphAdapter(IGraphStoragePort):
    def __init__(self):
        self.nodes: Dict[str, GraphNode] = {}         # uuid -> GraphNode
        self.name_index: Dict[str, str] = {}          # lowercase_name -> uuid
        self.edges: List[GraphEdge] = []

    def upsert_node(self, node_uuid: str, label: str, name: str, properties: dict) -> GraphNode:
        if node_uuid in self.nodes:
            existing = self.nodes[node_uuid]
            existing.label = label
            existing.properties.update(properties)
            return existing

        node = GraphNode(uuid=node_uuid, label=label, name=name, properties=properties)
        self.nodes[node_uuid] = node
        self.name_index[name.lower()] = node_uuid
        return node

    def upsert_edge(self, src_uuid: str, tgt_uuid: str, relation: str, weight: float = 1.0) -> GraphEdge:
        for edge in self.edges:
            if edge.src_uuid == src_uuid and edge.tgt_uuid == tgt_uuid and edge.relation == relation:
                edge.weight = max(edge.weight, weight)
                edge.expired = False
                return edge

        edge = GraphEdge(
            id=make_uuid(),
            src_uuid=src_uuid,
            tgt_uuid=tgt_uuid,
            relation=relation,
            weight=weight,
        )
        self.edges.append(edge)
        return edge

    def get_node_by_name(self, name: str) -> Optional[GraphNode]:
        uid = self.name_index.get(name.lower())
        if uid:
            return self.nodes.get(uid)
        for key, uid in self.name_index.items():
            if name.lower() in key or key in name.lower():
                return self.nodes.get(uid)
        return None

    def get_all_nodes(self) -> List[GraphNode]:
        return list(self.nodes.values())

    def get_all_edges(self) -> List[GraphEdge]:
        return [e for e in self.edges if not e.expired]

    def traverse_subgraph(self, start_uuid: str, max_depth: int, filters: dict) -> TraversalResult:
        visited: Dict[str, int] = {}
        queue = deque([(start_uuid, 0)])
        traversal_path = []
        path_edges = []

        while queue:
            current_uuid, depth = queue.popleft()
            if current_uuid in visited:
                continue
            visited[current_uuid] = depth
            traversal_path.append(current_uuid)

            if depth >= max_depth:
                continue

            for edge in self.edges:
                if edge.expired:
                    continue
                next_uuid = None
                if edge.src_uuid == current_uuid:
                    next_uuid = edge.tgt_uuid
                elif edge.tgt_uuid == current_uuid:
                    next_uuid = edge.src_uuid

                if next_uuid and next_uuid not in visited:
                    path_edges.append(edge.to_dict())
                    queue.append((next_uuid, depth + 1))

        return TraversalResult(
            visited_uuids=list(visited.keys()),
            traversal_path=traversal_path,
            path_edges=path_edges,
            depth_map=visited,
        )

    def human_override_delete_edge(self, src_uuid: str, tgt_uuid: str) -> bool:
        for edge in self.edges:
            if edge.src_uuid == src_uuid and edge.tgt_uuid == tgt_uuid:
                edge.expired = True
                return True
        return False


class InMemoryDocumentAdapter(IDocumentStoragePort):
    def __init__(self):
        self.docs: Dict[str, DocumentDTO] = {}  # entity_uuid -> DocumentDTO

    def save_wiki(self, entity_uuid: str, entity_name: str, content_markdown: str, version_hash: str) -> bool:
        self.docs[entity_uuid] = DocumentDTO(
            entity_uuid=entity_uuid,
            entity_name=entity_name,
            content_markdown=content_markdown,
            version_hash=version_hash,
        )
        return True

    def get_wiki(self, entity_uuid: str) -> Optional[DocumentDTO]:
        return self.docs.get(entity_uuid)

    def get_all_wikis(self) -> List[DocumentDTO]:
        return list(self.docs.values())
