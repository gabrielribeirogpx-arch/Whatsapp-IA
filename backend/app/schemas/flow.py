from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class NodeSchema(BaseModel):
    id: str
    type: Optional[str] = "default"
    data: Optional[Dict[str, Any]] = {}
    position: Optional[Dict[str, float]] = {"x": 0, "y": 0}


class EdgeSchema(BaseModel):
    id: Optional[str] = None
    source: Optional[str] = None
    target: Optional[str] = None


class FlowUpdate(BaseModel):
    nodes: List[NodeSchema]
    edges: Optional[List[EdgeSchema]] = []
