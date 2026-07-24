"""UTC daily aggregation. Run: python -m app.analytics.aggregate_product_metrics --date YYYY-MM-DD."""
import argparse
from datetime import date, datetime, time, timedelta, timezone
from sqlalchemy import delete, func, select
from app.database import SessionLocal
from app.core.config import settings
from app.models import ProductEvent, ProductMetricDaily
def main():
 p=argparse.ArgumentParser();p.add_argument('--date');p.add_argument('--start-date');p.add_argument('--end-date');p.add_argument('--tenant-id');p.add_argument('--dry-run',action='store_true');p.add_argument('--rebuild',action='store_true');a=p.parse_args()
 if not settings.product_analytics_aggregation_enabled: print('disabled');return
 start=date.fromisoformat(a.start_date or a.date or str(date.today()-timedelta(days=1)));end=date.fromisoformat(a.end_date or a.date or str(start));
 if a.rebuild and not a.dry_run and __import__('os').getenv('APP_ENV','').lower() in {'production','prod'}: raise SystemExit('Rebuild in production requires dry-run/export and explicit maintenance procedure.')
 db=SessionLocal()
 try:
  day=start
  while day<=end:
   q=select(ProductEvent.event_name,func.count()).where(ProductEvent.occurred_at>=datetime.combine(day,time.min,tzinfo=timezone.utc),ProductEvent.occurred_at<datetime.combine(day+timedelta(days=1),time.min,tzinfo=timezone.utc)).group_by(ProductEvent.event_name)
   if a.tenant_id:q=q.where(ProductEvent.tenant_id==a.tenant_id)
   rows=db.execute(q).all();print(day,len(rows))
   if not a.dry_run:
    if a.rebuild: db.execute(delete(ProductMetricDaily).where(ProductMetricDaily.date==day))
    now=datetime.now(timezone.utc)
    for name,value in rows: db.add(ProductMetricDaily(date=day,tenant_id=None,metric_name=name,dimension_key='all',dimension_value='all',metric_value=value,created_at=now,updated_at=now))
   day+=timedelta(days=1)
  if not a.dry_run:db.commit()
 finally:db.close()
if __name__=='__main__':main()
