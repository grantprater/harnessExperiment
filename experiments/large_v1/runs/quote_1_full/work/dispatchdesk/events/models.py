from dataclasses import dataclass

@dataclass(frozen=True)
class Event:
    id: int
    tenant: str
    status: str
    created_at: int
    payload: str = ""
