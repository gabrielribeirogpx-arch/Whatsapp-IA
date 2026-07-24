from __future__ import annotations
import json, logging, re, uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.product_analytics import ProductEvent, TenantActivationState
from .catalog import EVENTS, STATE_FIELDS
log=logging.getLogger(__name__); SENSITIVE=re.compile(r"password|secret|token|authorization|cookie|message|content|prompt|response|api[_-]?key|access[_-]?token|refresh[_-]?token|credit[_-]?card",re.I)
def _clean(v, depth=0):
    if depth>4: return "[truncated]"
    if isinstance(v,dict): return {str(k)[:80]:_clean(x,depth+1) for k,x in list(v.items())[:40] if not SENSITIVE.search(str(k))}
    if isinstance(v,list): return [_clean(x,depth+1) for x in v[:30]]
    if isinstance(v,str): return v[:512]
    return v if isinstance(v,(int,float,bool)) or v is None else str(v)[:512]
class ProductAnalyticsService:
 def __init__(self,db:Session): self.db=db
 def track(self,event_name,tenant_id=None,user_id=None,properties=None,context=None,idempotency_key=None,occurred_at=None,source='backend'):
  if not (settings.product_analytics_enabled and settings.product_analytics_capture_enabled) or event_name not in EVENTS: return False
  try:
   if idempotency_key and self.db.execute(select(ProductEvent.id).where(ProductEvent.idempotency_key==idempotency_key)).first(): log.info('PRODUCT_EVENT_DUPLICATE event=%s',event_name); return False
   now=datetime.now(timezone.utc); event=ProductEvent(event_id=uuid.uuid4(),tenant_id=tenant_id,user_id=user_id,event_name=event_name,event_version=1,source=source,occurred_at=occurred_at or now,received_at=now,created_at=now,properties=_clean(properties or {}),context=_clean(context or {}),idempotency_key=idempotency_key)
   self.db.add(event); self._state(event_name,tenant_id,event.occurred_at); self.db.flush(); log.info('PRODUCT_EVENT_ACCEPTED event=%s tenant=%s',event_name,tenant_id); return True
  except Exception: self.db.rollback(); log.exception('PRODUCT_EVENT_FAILED event=%s',event_name); return False
 def _state(self,name,tenant_id,at):
  field=STATE_FIELDS.get(name)
  if not tenant_id or not field:return
  state=self.db.get(TenantActivationState,tenant_id)
  if not state: state=TenantActivationState(tenant_id=tenant_id,updated_at=at); self.db.add(state)
  if getattr(state,field,None) is None:setattr(state,field,at)
  required=(state.whatsapp_connected_at, state.first_flow_published_at, state.first_message_received_at or state.first_message_sent_at)
  score=sum(bool(x) for x in required)+bool(name=='flow_execution_completed')
  state.activation_score=max(state.activation_score or 0,score)
  if all(required) and name=='flow_execution_completed' and state.activation_completed_at is None: state.activation_completed_at=at
  state.updated_at=at
