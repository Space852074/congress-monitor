# Congress Local Dashboard

A local dashboard for US House and Senate committee items.

## Features
- Local SQLite database (data/congress.db)
- Refresh from existing committee scrapers
- Local API endpoints and browser UI
- Filter by chamber, committee, and recent days

## Quick Start
1. Run run_dashboard.bat
2. Open http://127.0.0.1:8765

## Commands
- python dashboard/app.py initdb
- python dashboard/app.py refresh --target all
- python dashboard/app.py serve --host 127.0.0.1 --port 8765 --bootstrap

## API
- GET /api/health
- GET /api/stats
- GET /api/committees?chamber=House&limit=40
- GET /api/items?chamber=House&committee=china&days=30&limit=120
- GET /api/refresh?target=all
 
## Dependencies 
- pip install -r dashboard\requirements.txt
