from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.database import get_db
from app.models import ProductEvent, Tenant, TenantActivationState, TenantUser
from app.routers.account import get_current_user
from app.services.tenant_service import get_current_tenant
from app.services.audit_service import write_audit_log
from app.analytics.catalog import EVENTS
from app.analytics.service import ProductAnalyticsService
router=APIRouter(prefix='/product-analytics',tags=['product-analytics']); admin_router=APIRouter(prefix='/admin/growth',tags=['admin-growth'])
class EventIn(BaseModel):
 event_name:str=Field(max_length=96); properties:dict=Field(default_factory=dict); context:dict=Field(default_factory=dict); idempotency_key:str|None=Field(default=None,max_length=255); occurred_at:datetime|None=None
class BatchIn(BaseModel): events:list[EventIn]=Field(min_length=1,max_length=50)
def enabled():
 if not settings.product_analytics_enabled: raise HTTPException(503,detail={'status':'disabled'})
def admin(user=Depends(get_current_user)):
 if user.role not in {'owner','admin'}: raise HTTPException(403,'Acesso administrativo necessário')
 return user
@router.post('/events')
def capture(payload:EventIn, db:Session=Depends(get_db),tenant:Tenant=Depends(get_current_tenant),user:TenantUser=Depends(get_current_user)):
 enabled()
 if payload.event_name not in EVENTS: raise HTTPException(422,'Evento não permitido')
 stored=ProductAnalyticsService(db).track(payload.event_name,tenant.id,user.id,payload.properties,payload.context,payload.idempotency_key,payload.occurred_at,source='frontend'); db.commit(); return {'accepted':stored}
@router.post('/events/batch')
def capture_batch(payload:BatchIn, db:Session=Depends(get_db),tenant:Tenant=Depends(get_current_tenant),user:TenantUser=Depends(get_current_user)):
 enabled(); service=ProductAnalyticsService(db); accepted=0
 for item in payload.events:
  if item.event_name not in EVENTS: continue
  accepted+=bool(service.track(item.event_name,tenant.id,user.id,item.properties,item.context,item.idempotency_key,item.occurred_at,source='frontend'))
 db.commit(); return {'accepted':accepted,'received':len(payload.events)}
def since(days:int): return datetime.now(timezone.utc)-timedelta(days=min(max(days,1),90))
@admin_router.get('/overview')
def overview(days:int=30,db:Session=Depends(get_db),user=Depends(admin),request:Request=None):
 if not settings.product_analytics_enabled:return {'status':'disabled'}
 start=since(days); counts=dict(db.execute(select(ProductEvent.event_name,func.count()).where(ProductEvent.occurred_at>=start).group_by(ProductEvent.event_name)).all()); states=db.execute(select(TenantActivationState)).scalars().all(); write_audit_log(db,action='GROWTH_OVERVIEW_VIEWED',tenant_id=user.tenant_id,user_id=user.id,entity_type='growth',request=request);db.commit()
 return {'status':'enabled','period_days':days,'cards':{'registrations':counts.get('registration_completed',0),'trials':counts.get('trial_started',0),'onboarding_completed':counts.get('onboarding_completed',0),'whatsapp_connected':counts.get('whatsapp_connected',0),'upgrade_clicks':counts.get('upgrade_clicked',0),'checkouts_started':counts.get('checkout_started',0),'subscriptions_activated':counts.get('subscription_activated',0),'activated_tenants':sum(s.activation_completed_at is not None for s in states),'ai_activated_tenants':sum(s.first_ai_execution_at is not None for s in states)},'revenue':{'status':'unavailable','mrr':None,'arr':None,'churn':None}}
@admin_router.get('/funnel')
def funnel(days:int=30,db:Session=Depends(get_db),user=Depends(admin)):
 if not settings.product_analytics_enabled:return {'status':'disabled','steps':[]}
 start=since(days); steps=['registration_completed','trial_started','onboarding_started','whatsapp_connected','first_flow_created','first_flow_published','first_message_received','first_ai_execution','onboarding_completed']; counts=dict(db.execute(select(ProductEvent.event_name,func.count(func.distinct(ProductEvent.tenant_id))).where(ProductEvent.occurred_at>=start,ProductEvent.event_name.in_(steps)).group_by(ProductEvent.event_name)).all()); base=counts.get(steps[0],0); prev=base
 out=[]
 for name in steps:
  count=counts.get(name,0); out.append({'event_name':name,'count':count,'conversion_from_previous':round(count/prev*100,2) if prev else 0,'conversion_cumulative':round(count/base*100,2) if base else 0,'abandonment':max(prev-count,0)});prev=count
 return {'status':'enabled','small_sample':base<30,'steps':out}
@admin_router.get('/timeseries')
def timeseries(days:int=30,db:Session=Depends(get_db),user=Depends(admin)):
 if not settings.product_analytics_enabled:return {'status':'disabled','series':[]}
 rows=db.execute(select(func.date(ProductEvent.occurred_at),ProductEvent.event_name,func.count()).where(ProductEvent.occurred_at>=since(days)).group_by(func.date(ProductEvent.occurred_at),ProductEvent.event_name).order_by(func.date(ProductEvent.occurred_at))).all();return {'status':'enabled','timezone':'UTC','series':[{'date':str(d),'event_name':n,'value':v} for d,n,v in rows]}
@admin_router.get('/tenants')
def tenants(page:int=1,page_size:int=25,db:Session=Depends(get_db),user=Depends(admin)):
 page_size=min(max(page_size,1),100); rows=db.execute(select(Tenant,TenantActivationState).outerjoin(TenantActivationState,Tenant.id==TenantActivationState.tenant_id).offset((max(page,1)-1)*page_size).limit(page_size)).all();return {'items':[{'tenant_id':str(t.id),'name':t.name,'plan':t.plan,'activation':bool(s and s.activation_completed_at),'activation_score':s.activation_score if s else 0} for t,s in rows],'page':page}
@admin_router.get('/tenants/{tenant_id}')
def tenant_detail(tenant_id:str,db:Session=Depends(get_db),user=Depends(admin)):
 tenant=db.get(Tenant,tenant_id)
 if not tenant:raise HTTPException(404,'Tenant não encontrado')
 state=db.get(TenantActivationState,tenant.id); events=db.execute(select(ProductEvent).where(ProductEvent.tenant_id==tenant.id).order_by(ProductEvent.occurred_at.desc()).limit(50)).scalars().all();return {'tenant_id':str(tenant.id),'plan':tenant.plan,'activation_state':None if not state else {'activation_completed_at':state.activation_completed_at,'activation_score':state.activation_score,'ai_activated':bool(state.first_ai_execution_at)},'events':[{'event_name':e.event_name,'occurred_at':e.occurred_at,'source':e.source} for e in events]}
@admin_router.get('/activation')
def activation(db:Session=Depends(get_db),user=Depends(admin)):
 if not settings.product_analytics_enabled:return {'status':'disabled'}
 states=db.execute(select(TenantActivationState)).scalars().all(); return {'status':'enabled','activated':sum(x.activation_completed_at is not None for x in states),'ai_activated':sum(x.first_ai_execution_at is not None for x in states)}
