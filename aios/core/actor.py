"""Who is acting. The founder is the only actor that can approve."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    kind: str  # "founder" | "agent" | "system"
    id: str = ""

    def __str__(self) -> str:
        if self.kind == "founder":
            return "founder"
        if self.kind == "system":
            return f"system:{self.id}" if self.id else "system"
        return f"agent:{self.id}"

    @property
    def is_founder(self) -> bool:
        return self.kind == "founder"

    @property
    def is_agent(self) -> bool:
        return self.kind == "agent"


FOUNDER = Actor("founder")
SYSTEM = Actor("system")


def agent(agent_id: str) -> Actor:
    return Actor("agent", agent_id)
