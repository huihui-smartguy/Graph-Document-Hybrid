import hashlib
import os
import re
from typing import Dict, List, Optional

from core.models import DocumentDTO
from core.ports import IDocumentStoragePort
from engines.provider import get_provider

WIKI_CREATE_SYSTEM = """You are a knowledge base writer. Create a structured Markdown wiki page for the given entity.

The wiki page must follow this exact structure:

---
entity: {entity_name}
label: {entity_label}
updated: {date}
---

## Core Summary
[2-3 sentence overview of who/what this entity is]

## Key Facts
- [fact 1]
- [fact 2]
- [fact 3]

## Chronicle
[Brief timeline of significant events or milestones, one per bullet]

## Relationships
[Known connections to other entities]

## Notes
[Additional context or observations]

Write in a concise, encyclopedic style. Use only the facts provided — do not invent details."""

WIKI_UPDATE_SYSTEM = """You are a knowledge base editor applying the Read-Reflect-Overwrite pattern.

Given an existing wiki page and new information, produce an updated wiki page that:
1. Preserves all existing accurate information
2. Integrates new facts naturally
3. Removes any contradictions (new info takes precedence)
4. Maintains the same Markdown structure

Return ONLY the complete updated wiki page content, no explanation."""


class LLMWikiEngine:
    def __init__(self, docs: IDocumentStoragePort):
        self.docs = docs
        self.provider = get_provider()

    def _hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def get_or_create_wiki(
        self,
        entity_uuid: str,
        entity_name: str,
        entity_label: str,
        new_facts: str,
    ) -> DocumentDTO:
        existing = self.docs.get_wiki(entity_uuid)

        if existing is None:
            prompt = (
                f"Create a wiki page for this entity.\n\n"
                f"Entity Name: {entity_name}\n"
                f"Entity Type: {entity_label}\n\n"
                f"Known facts:\n{new_facts}"
            )
            system_text = WIKI_CREATE_SYSTEM.replace("{entity_name}", entity_name).replace(
                "{entity_label}", entity_label
            ).replace("{date}", "2026-05-06")

            response = self.provider.messages_create(
                model=os.getenv("VGD_WIKI_MODEL", "claude-haiku-4-5"),
                max_tokens=4096,
                system=[
                    {
                        "type": "text",
                        "text": system_text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": prompt}],
            )
            content = self.provider.extract_text(response)
        else:
            prompt = (
                f"Current wiki page:\n\n{existing.content_markdown}\n\n"
                f"---\n\nNew information to integrate:\n{new_facts}"
            )
            response = self.provider.messages_create(
                model=os.getenv("VGD_WIKI_MODEL", "claude-haiku-4-5"),
                max_tokens=4096,
                system=[
                    {
                        "type": "text",
                        "text": WIKI_UPDATE_SYSTEM,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": prompt}],
            )
            content = self.provider.extract_text(response)

        version_hash = self._hash(content)
        self.docs.save_wiki(entity_uuid, entity_name, content, version_hash)
        return self.docs.get_wiki(entity_uuid)

    def get_multi_wiki_context(self, entity_uuids: List[str], max_entities: int = 6) -> str:
        sections = []
        for uid in entity_uuids[:max_entities]:
            doc = self.docs.get_wiki(uid)
            if doc:
                sections.append(f"### Wiki: {doc.entity_name}\n\n{doc.content_markdown}")
        if not sections:
            return "No wiki pages available yet."
        return "\n\n---\n\n".join(sections)
