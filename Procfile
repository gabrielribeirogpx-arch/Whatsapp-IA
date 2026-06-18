release: if [ -f backend/release.sh ]; then bash backend/release.sh; else bash release.sh; fi
web: cd backend && bash start.sh
worker: python backend/worker_rq.py
