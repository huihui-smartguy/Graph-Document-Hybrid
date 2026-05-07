from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from core.models import DocumentDTO, GraphEdge, GraphNode, TraversalResult


class IGraphStoragePort(ABC):
    @abstractmethod
    def upsert_node(self, node_uuid: str, label: str, name: str, properties: dict) -> GraphNode:
        ...

    @abstractmethod
    def upsert_edge(self, src_uuid: str, tgt_uuid: str, relation: str, weight: float = 1.0) -> GraphEdge:
        ...

    @abstractmethod
    def get_node_by_name(self, name: str) -> Optional[GraphNode]:
        ...

    @abstractmethod
    def get_all_nodes(self) -> List[GraphNode]:
        ...

    @abstractmethod
    def get_all_edges(self) -> List[GraphEdge]:
        ...

    @abstractmethod
    def traverse_subgraph(self, start_uuid: str, max_depth: int, filters: dict) -> TraversalResult:
        ...

    @abstractmethod
    def human_override_delete_edge(self, src_uuid: str, tgt_uuid: str) -> bool:
        ...


class IDocumentStoragePort(ABC):
    @abstractmethod
    def save_wiki(self, entity_uuid: str, entity_name: str, content_markdown: str, version_hash: str) -> bool:
        ...

    @abstractmethod
    def get_wiki(self, entity_uuid: str) -> Optional[DocumentDTO]:
        ...

    @abstractmethod
    def get_all_wikis(self) -> List[DocumentDTO]:
        ...
