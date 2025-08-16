# Helldivers Dropzone — Cache-First Loadout Generator (Subjective Programming Demo)
  
A backend service (FastAPI + OpenAI) that recommends Helldivers 2 loadouts using a **hybrid approach**:

* **Objective rails (code):** hard constraints, validation, novelty rules, caching.
* **Subjective pass (LLM):** naming, lore, and play guidance inside strict bounds.

The result is a production-style example of **subjective programming**: use an LLM to pool patterns and fuzzy preferences, then run the output through deterministic software so the final result is **consistent, safe, and shippable**.

> This repository contains the **backend** only. A separate UI can call these endpoints or poll the cache to implement a “smart-lock” UX (lock after generate; unlock when the cache baseline changes).

---

## Why this project exists (Subjective Programming)

**Subjective programming** is a pattern where:

1. Code enforces structure, constraints, and safety (objective).
2. The model fills in the subjective parts (naming, tone, stylistic choices).
3. Outputs are validated, versioned, and cached before reaching users.

This repo demonstrates that pattern end-to-end:

* **Constrained selection** from a curated pool (no model hallucinated items).
* **Deterministic validators** ensure: exactly 4 stratagems, exactly 1 support weapon, ≤1 backpack, no duplicates.
* **Novelty controls** prevent repetition across the 12 role×enemy pairs.
* **Cache-first API** returns instantly, then **background refreshes** with a new baseline the client can detect.

---

## Features at a glance

* **Cache-first responses:** `POST /generate_loadout` returns the latest cached build immediately.
* **Background refresh:** Generates a new candidate in the background and updates the cache.
* **Hard constraints:** `validate_stratagems` guarantees the stratagem mix is valid.
* **Novelty & distribution:**

  * `differs_by_three_or_more` enforces a meaningful change vs. the previous build.
  * `replace_overused_items` caps popular items across the whole cache.
* **LLM only where it helps:**

  * `generate_helldivers_loadout` selects from a provided pool.
  * `rewrite_flavor_text` produces name/lore/how-to (subjective layer) after rules lock the structure.

---

## Repository layout

```
Helldivers_Dropzone/
├── Python_Classes/
│   ├── main.py                # FastAPI app (endpoints, CORS, static mounts)
│   ├── ClassPicker.py         # generation pipeline + validators + cache update
│   ├── OpenAIRequest.py       # OpenAI calls (reads OPENAI_API_KEY from .env)
│   └── utils.py               # helpers: JSON IO, scoring, novelty, coercion
├── json/
│   ├── helldivers_complete.json        # curated dataset (inputs/pool)
│   ├── Helldivers_Backup_Classes.json  # safe fallback builds (12 pairs)
│   └── helldivers_cached_loadouts.json # runtime cache (ignored by git)
├── requirements.txt
└── README.md
```

> Your `.gitignore` should **ignore** `json/helldivers_cached_loadouts.json` (runtime cache) and **never** track `.env`.

---

## The JSON files (what they are & how they’re used)

* **`json/helldivers_complete.json`**
  Curated source data the generator filters to build candidate pools.
  Each entry includes fields like `Type`, `Damage Type`, per-enemy effectiveness scores (e.g. `automatons_effectiveness`), `special_traits`, `goal`, and for stratagems a `category` and `squad_role`.

* **`json/Helldivers_Backup_Classes.json`**
  A “safe fallback” of 12 static builds (one per `Role × Enemy`).
  Used when the cache doesn’t have a valid entry yet. Guarantees the API always returns something.

* **`json/helldivers_cached_loadouts.json`** (**runtime cache; do not commit**)
  Updated by the background task after `/generate_loadout`. Keys are `"Role_Enemy"`.
  The API reads this first to respond instantly, and the frontend can poll and **unlock** once it detects a new `loadout_name` (or a version field if you add one).

---

## How it works (pipeline)

1. **Client calls** `POST /generate_loadout` with `{ role?, enemy? }`.

   * If `role`/`enemy` are omitted, the service picks them (`choose_role`, `choose_faction`).
   * The API returns the **current cached** build for that pair immediately.

2. **Background task** kicks off:

   * Build a **filtered pool** from `helldivers_complete.json` (role/enemy-aware).
   * Ask the LLM to **select** items *from that pool* (`generate_helldivers_loadout`).
   * **Validate & repair**:

     * `validate_stratagems`: exactly 4, 1 support, ≤1 backpack, no dups; fill any missing gear.
     * `replace_overused_items`: avoid global overuse across the 12 pairs.
     * `differs_by_three_or_more`: ensure material change vs. previous build.
   * Ask the LLM to **rewrite** flavor text (how-to, objective, lore, **loadout\_name**).
   * **Save** to `helldivers_cached_loadouts.json`.

3. **Client smart-lock** (optional, in your UI):
   Lock the button after generate; poll `/get_cached_loadout?role=…&enemy=…`; unlock when the `loadout_name` changes (or after a timeout).

---

## API

### `POST /generate_loadout`

Returns the current cached build immediately; triggers a background refresh.

**Request**

```json
{ "role": "Saboteur", "enemy": "automatons" }
```

Both fields are optional.

**Response** (shape; fields elided for brevity)

```json
{
  "role": "Saboteur",
  "enemy": "automatons",
  "loadout": {
    "primary": { "name": "…" },
    "secondary": { "name": "…" },
    "grenade": { "name": "…" },
    "armor_passive": { "name": "…" }
  },
  "stratagems": [
    { "name": "…", "category": "Support Weapons" },
    { "name": "…", "category": "…" },
    { "name": "…", "category": "…" },
    { "name": "…", "category": "…" }
  ],
  "how_to_play": { "solo": "…", "co_op": "…", "positioning": "…", "combo_flow": "…" },
  "objective": "…",
  "lore": "…",
  "loadout_name": "…"
}
```

### `GET /get_cached_loadout?role=…&enemy=…`

Returns the latest cached build for that pair (no background work).

---

## Install & run (local)

**Requirements**

* Python 3.10+ recommended
* An OpenAI API key (stored in `.env`)

**Setup**

```bash
cd Helldivers_Dropzone

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# Create your .env (never commit)
cp .env.example .env            # if you add an example; otherwise create it
# then edit .env and add:
# OPENAI_API_KEY=sk-...

# Run from inside Python_Classes so relative paths to ../json work unchanged
cd Python_Classes
uvicorn main:app --reload --port 8000
```

**Smoke tests**

```bash
# Replace role/enemy as desired
curl -s -X POST http://localhost:8000/generate_loadout \
  -H "Content-Type: application/json" \
  -d '{"role":"Saboteur","enemy":"automatons"}' | jq .

curl -s "http://localhost:8000/get_cached_loadout?role=Saboteur&enemy=automatons" | jq .
```

---

## Security & secrets

* **Never commit** your `.env`. Keep only an `.env.example` with variable names.
* Rotate any key that ever appeared in Git history.
* `OpenAIRequest.py` loads the key from env:

  ```py
  from dotenv import load_dotenv; load_dotenv()
  import os
  api_key = os.getenv("OPENAI_API_KEY")
  ```

---

## Implementation details (highlights)

* **Filtered pools** (`generate_filtered_pool`) bias by enemy type and effectiveness; scoring uses `calculate_weight`.
* **Validation & repair**

  * `validate_stratagems` ensures exactly 4 stratagems, 1 support, ≤1 backpack, no duplicates; fills any missing gear.
  * `trim_to_four` prioritizes (1 support, 1 backpack if present, then top scores).
* **Novelty & distribution**

  * `differs_by_three_or_more` requires ≥3 item changes vs. previous loadout.
  * `replace_overused_items` substitutes over-used gear/stratagems across the cache.
* **Cache shape compatibility**

  * `extract_valid` tolerates both raw dicts and legacy `[dict, ok]` entries in the cache for robustness.

---

## Roadmap (nice upgrades)

* **JSON-only model responses** using `response_format={"type":"json_object"}` + Pydantic schema validation.
* **Atomic cache writes** (`tempfile` + `os.replace`) to prevent partial files.
* **Version field** (e.g., `updated_at` or `rev`) in cache entries so clients unlock on version change rather than `loadout_name`.
* **Metrics**: cache hit rate, unlock latency, generation failures, token/cost usage.
* **Tests**: unit tests for validators/novelty; integration test stubbing OpenAI.

---

## Troubleshooting

* **`OPENAI_API_KEY is not set`**
  Create `.env` next to your Python files and set the key, or export it in your shell.
* **CORS in a separate frontend**
  Add your UI origin to the CORS middleware in `main.py`.
* **Cache not updating**
  Ensure `json/helldivers_complete.json` exists; background refresh only runs when the data file is present.
* **Icons/Static**
  If your UI relies on `/icons/**`, serve them from your frontend or mount a static directory in FastAPI.

---

## License

Personal project; no license specified yet. (Add MIT/Apache-2.0 here if you intend to open-source.)

---

## Credits

Built as a practical exploration of **subjective programming** for configuration/recommendation under constraints, using Helldivers 2 as an engaging domain.

