"""Short-term conversation state (task 8.8)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Turn:
    question: str
    answer: str
    intent: str
    target_module: str | None


@dataclass
class ConversationSession:
    session_id: str
    turns: list[Turn] = field(default_factory=list)
    max_turns: int = 20

    def add(self, question: str, answer: str, intent: str, target_module: str | None) -> None:
        self.turns.append(Turn(question, answer, intent, target_module))
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

    def last_module(self) -> str | None:
        for t in reversed(self.turns):
            if t.target_module:
                return t.target_module
        return None