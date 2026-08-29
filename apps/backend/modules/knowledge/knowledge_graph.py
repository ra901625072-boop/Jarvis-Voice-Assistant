import re
import logging

logger = logging.getLogger("JARVIS.KnowledgeGraph")

class KnowledgeGraphMixin:
    def add_entity(
        self, name: str, entity_type: str, description: str = ""
    ) -> None:
        """Add or update a knowledge graph node."""
        ts = self._now()
        with self._lock.write_lock():
            self.dbs["conversations"].execute(
                """INSERT OR REPLACE INTO entities (name, entity_type, description, created_at)
                   VALUES (?, ?, ?, ?)""",
                (name, entity_type, description, ts),
            )
            self._commit()

    def add_relationship(
        self,
        entity_a: str,
        relation: str,
        entity_b: str,
        confidence: float = 1.0,
    ) -> None:
        """Add a directed relationship between two entities."""
        ts = self._now()
        with self._lock.write_lock():
            self.dbs["conversations"].execute(
                """INSERT OR REPLACE INTO relationships
                   (entity_a, relation, entity_b, confidence, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (entity_a, relation, entity_b, confidence, ts),
            )
            self._commit()

    def get_knowledge_context(self, entity_name: str) -> str:
        """
        Return a formatted string of all relationships for an entity —
        used for reasoning beyond vector similarity.
        """
        with self._lock.read_lock():
            outgoing = self.dbs["conversations"].execute(
                "SELECT relation, entity_b FROM relationships WHERE entity_a = ?",
                (entity_name,),
            ).fetchall()
            incoming = self.dbs["conversations"].execute(
                "SELECT entity_a, relation FROM relationships WHERE entity_b = ?",
                (entity_name,),
            ).fetchall()
            entity = self.dbs["conversations"].execute(
                "SELECT entity_type, description FROM entities WHERE name = ?",
                (entity_name,),
            ).fetchone()

        if not outgoing and not incoming and not entity:
            return ""

        lines = [f"Entity: {entity_name}"]
        if entity:
            lines.append(f"  Type: {entity[0]}  |  {entity[1]}")
        for rel, target in outgoing:
            lines.append(f"  → {rel} → {target}")
        for source, rel in incoming:
            lines.append(f"  ← {rel} ← {source}")
        return "\n".join(lines)

    def _build_kg_context(self, query: str) -> str:
        """Extract knowledge-graph context relevant to the query."""
        try:
            # Find entities whose names appear in the query
            words = re.findall(r"\b\w{4,}\b", query.lower()) if query else []
            lines = []
            for word in words[:5]:
                with self._lock.read_lock():
                    rows = self.dbs["conversations"].execute(
                        "SELECT name FROM entities WHERE LOWER(name) LIKE ?",
                        (f"%{word}%",),
                    ).fetchall()
                for (name,) in rows:
                    ctx = self.get_knowledge_context(name)
                    if ctx:
                        lines.append(ctx)
            return "\n".join(lines[:6])  # cap at 6 entity blocks
        except Exception as e:
            logger.debug(f"KG context build failed: {e}")
            return ""
