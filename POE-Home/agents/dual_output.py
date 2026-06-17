from typing import Any, Optional

from pydantic import BaseModel


class VisualPayload(BaseModel):
    type: str
    data: dict[str, Any] = {}
    template: Optional[str] = None


class DualOutput(BaseModel):
    verbal: str
    visual: Optional[VisualPayload] = None
