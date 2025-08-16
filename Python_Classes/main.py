from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import os

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
from utils import (
    load_json, choose_role,
    choose_faction
)
from ClassPicker import update_cached_loadout

CACHE_FILE = "../json/helldivers_cached_loadouts.json"
DATA_FILE = "../json/helldivers_complete.json"
BACKUP_FILE = "../json/Helldivers_Backup_Classes.json"
ROLES = ["Crowd Control", "Anti-Tank", "Saboteur", "Stratagem Support"]
ENEMIES = ["automatons", "terminids", "illuminate"]

app = FastAPI()


app.mount("/static", StaticFiles(directory="../static"), name="static")
app.mount("/icons", StaticFiles(directory="../icons"), name="icons")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class LoadoutRequest(BaseModel):
    role: Optional[str] = None
    enemy: Optional[str] = None


def extract_valid(entry):
    """
    Valid if:
    - [dict, True] with dict containing "loadout" & "stratagems"
    - or direct dict with the same keys
    """
    def is_complete_dict(d):
        return isinstance(d, dict) and "loadout" in d and "stratagems" in d

    # Handle [data, bool] structure
    if isinstance(entry, list) and len(entry) == 2:
        data, ok = entry
        if ok and is_complete_dict(data):
            return data
        return None

    # Handle legacy raw dict structure
    if is_complete_dict(entry):
        return entry

    return None

def get_loadout(role: str, enemy: str):
    key = f"{role}_{enemy}"

    # 1) Check cache
    cache = load_json(CACHE_FILE)
    loadout = extract_valid(cache.get(key))
    if loadout:
        return loadout

    # 2) Fallback to backup
    backup = load_json(BACKUP_FILE)
    loadout = extract_valid(backup.get(key))
    return loadout or {}


@app.get("/")
def serve_index():
    return FileResponse("../templates/index.html")


@app.post("/generate_loadout")
def generate_loadout(request: LoadoutRequest, background_tasks: BackgroundTasks):
    role = request.role or choose_role()
    enemy = request.enemy or choose_faction()

    loadout = get_loadout(role, enemy)

    # Always include the role and enemy in the JSON
    response = {
        "role": role,
        "enemy": enemy,
        **loadout
    }

    # Schedule background update
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            helldivers_data = json.load(f)
        background_tasks.add_task(update_cached_loadout, role, enemy, helldivers_data)

    return response


@app.get("/get_cached_loadout")
def get_cached_loadout(role: str, enemy: str):
    loadout = get_loadout(role, enemy)
    return {"role": role, "enemy": enemy, **loadout}
