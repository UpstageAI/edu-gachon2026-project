from typing import Optional

from pydantic import BaseModel


class RetrievedDocument(BaseModel):
    id: str
    question: str
    answer: str
    category: str
    distance: Optional[float] = None
    source_url: Optional[str] = None
