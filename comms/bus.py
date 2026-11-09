"""Message bus: the explicit communication layer between agents.

Channels
- "analyst": broadcasts from the analyst agent (market summary, consensus price estimate).
- "beliefs": each trader's private estimate of the equilibrium price, posted every round.
             The analyst aggregates these, which is how disagreement between traders is resolved
             into a shared signal (consensus = median, disagreement = spread).
- "chat":    optional cheap talk between traders (public, unenforceable). Off by default.

Every message is logged so transcripts can be analysed and shown in the dashboard.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, asdict, field


@dataclass
class Message:
    sender: str
    channel: str
    content: str
    period: int
    round: int
    data: dict = field(default_factory=dict)   # structured payload (e.g. {"belief": 101.5})

    def to_dict(self) -> dict:
        return asdict(self)


class MessageBus:
    def __init__(self, enabled_channels: set[str] | None = None):
        self.enabled = enabled_channels if enabled_channels is not None else {"analyst", "beliefs"}
        self.log: list[Message] = []
        self._lock = threading.Lock()

    def publish(self, msg: Message) -> bool:
        if msg.channel not in self.enabled:
            return False
        with self._lock:
            self.log.append(msg)
        return True

    def read(self, channel: str, since_period: int | None = None, last_n: int | None = None,
             exclude_sender: str | None = None) -> list[Message]:
        msgs = [m for m in self.log if m.channel == channel
                and (since_period is None or m.period >= since_period)
                and m.sender != exclude_sender]
        return msgs[-last_n:] if last_n else msgs

    def view_for(self, agent_id: str, period: int, last_n: int = 5) -> list[dict]:
        """What a trader sees: recent analyst broadcasts and chat from others (not raw beliefs)."""
        out = [m.to_dict() for m in self.read("analyst", last_n=2)]
        out += [m.to_dict() for m in self.read("chat", since_period=period, last_n=last_n, exclude_sender=agent_id)]
        return out
