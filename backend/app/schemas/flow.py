from pydantic import BaseModel, ConfigDict
from typing import Any, Dict, List, Optional


class NodeSchema(BaseModel):
    id: str
    type: Optional[str] = "default"
    data: Optional[Dict[str, Any]] = {}
    position: Optional[Dict[str, float]] = {"x": 0, "y": 0}


class EdgeSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    source: Optional[str] = None
    target: Optional[str] = None
    sourceHandle: Optional[str] = None
    targetHandle: Optional[str] = None
    type: Optional[str] = None
    label: Optional[Any] = None
    data: Optional[Dict[str, Any]] = None


class FlowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_type: Optional[str] = None
    trigger_value: Optional[str] = None
    nodes: Optional[List[NodeSchema]] = None
    edges: Optional[List[EdgeSchema]] = None
