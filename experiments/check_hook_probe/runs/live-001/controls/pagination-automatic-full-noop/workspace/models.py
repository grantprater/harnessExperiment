from dataclasses import dataclass

@dataclass(frozen=True)
class Record:
    id: int
    owner: str
    status: str
    created_at: int
