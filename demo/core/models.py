from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time
import uuid


@dataclass
class GraphNode:
    uuid: str
    label: str  # PERSON, COMPANY, EVENT, PROJECT, LOCATION, OTHER
    name: str
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "uuid": self.uuid,
            "label": self.label,
            "name": self.name,
            "properties": self.properties,
            "created_at": self.created_at,
        }


@dataclass
class GraphEdge:
    id: str
    src_uuid: str
    tgt_uuid: str
    relation: str
    weight: float = 1.0
    expired: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "src_uuid": self.src_uuid,
            "tgt_uuid": self.tgt_uuid,
            "relation": self.relation,
            "weight": self.weight,
            "expired": self.expired,
        }


@dataclass
class DocumentDTO:
    entity_uuid: str
    entity_name: str
    content_markdown: str
    version_hash: str
    updated_at: float = field(default_factory=time.time)


@dataclass
class TripleDTO:
    subject: str
    subject_label: str
    predicate: str
    object: str
    object_label: str


@dataclass
class TraversalResult:
    visited_uuids: List[str]
    traversal_path: List[str]
    path_edges: List[Dict]
    depth_map: Dict[str, int] = field(default_factory=dict)


def make_uuid() -> str:
    return str(uuid.uuid4())
