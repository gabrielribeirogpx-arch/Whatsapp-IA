"""Conservative activation backfill from already recorded product events."""
import argparse
from sqlalchemy import select
from app.database import SessionLocal
from app.models import ProductEvent
from app.analytics.service import ProductAnalyticsService
def main():
 p=argparse.ArgumentParser();p.add_argument('--dry-run',action='store_true');a=p.parse_args();db=SessionLocal()
 try:
  events=db.execute(select(ProductEvent).where(ProductEvent.tenant_id.is_not(None)).order_by(ProductEvent.occurred_at)).scalars()
  count=0
  for e in events:
   count+=1
   if not a.dry_run: ProductAnalyticsService(db)._state(e.event_name,e.tenant_id,e.occurred_at)
  if not a.dry_run:db.commit()
  print(f'processed={count} dry_run={a.dry_run}')
 finally:db.close()
if __name__=='__main__':main()
