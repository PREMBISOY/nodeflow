from __future__ import annotations

from collections import defaultdict, deque
from uuid import UUID

from app.models import Relationship


class DependencyGraph:
    """Small bidirectional graph built from component relationships."""

    def __init__(self, relationships: list[Relationship]):
        self.outgoing: dict[UUID, set[UUID]] = defaultdict(set)
        self.incoming: dict[UUID, set[UUID]] = defaultdict(set)
        for relation in relationships:
            self.outgoing[relation.source_component_id].add(relation.target_component_id)
            self.incoming[relation.target_component_id].add(relation.source_component_id)

    def neighbors(self, component_id: UUID) -> set[UUID]:
        return self.outgoing[component_id] | self.incoming[component_id]

    def related(self, component_id: UUID, max_depth: int = 2) -> dict[UUID, int]:
        distances: dict[UUID, int] = {}
        queue: deque[tuple[UUID, int]] = deque([(component_id, 0)])
        seen = {component_id}
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbor in self.neighbors(current):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                distances[neighbor] = depth + 1
                queue.append((neighbor, depth + 1))
        return distances
