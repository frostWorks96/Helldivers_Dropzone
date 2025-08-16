# Helldivers Loadout Backend (Subjective Programming Demo)

Cache-first FastAPI service that returns a Helldivers 2 loadout instantly from a JSON cache and refreshes it in the background using an LLM. The generator is **constrained** by a curated pool and **validated** by deterministic rules (one support weapon, ≤1 backpack, no duplicates), then the model rewrites the flavor text & name. The UI (separate project) polls `/get_cached_loadout` and unlocks when the baseline changes.

## Endpoints
- `POST /generate_loadout` — returns `{ role, enemy, ...loadout }` from cache; schedules a background refresh.
- `GET /get_cached_loadout?role=...&enemy=...` — returns the latest cached loadout for that pair.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate   # on Windows: .venv\Scripts\activate
pip install -r requirements.txt

# make your real .env from the example:
cp .env.example .env
# then edit .env and set OPENAI_API_KEY

uvicorn main:app --reload --port 8000

Now try:

curl -s -X POST http://localhost:8000/generate_loadout -H "Content-Type: application/json" -d '{"role":"Saboteur","enemy":"automatons"}' | jq .
curl -s "http://localhost:8000/get_cached_loadout?role=Saboteur&enemy=automatons" | jq .


The service works even without the large data files; it serves cached/backup if present and schedules a refresh only when the data file exists.
