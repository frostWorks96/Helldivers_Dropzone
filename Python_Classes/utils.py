import json
import os
import random
from collections import Counter

CACHE_FILE = "../json/helldivers_cached_loadouts.json"
BACKUP_FILE = "../json/Helldivers_Backup_Classes.json"
ROLES = ["Crowd Control", "Anti-Tank", "Saboteur", "Stratagem Support"]
ENEMIES = ["automatons", "terminids", "illuminate"]

# -------------------- JSON & Cache Helpers --------------------

def load_json(file_path: str):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

def build_initial_cache():
    """Creates 12 placeholder loadouts if no cache exists yet."""
    cache = {}
    for role in ROLES:
        for enemy in ENEMIES:
            key = f"{role}_{enemy}"
            cache[key] = {
                "role": role,
                "enemy": enemy,
                "loadout": {
                    "primary": {"name": f"Primary_{role}_{enemy}"},
                    "secondary": {"name": f"Secondary_{role}_{enemy}"},
                    "grenade": {"name": f"Grenade_{role}_{enemy}"},
                    "armor_passive": {"name": f"Armor_{role}_{enemy}"}
                },
                "stratagems": [
                    {"name": f"Stratagem1_{role}_{enemy}"},
                    {"name": f"Stratagem2_{role}_{enemy}"},
                    {"name": f"Stratagem3_{role}_{enemy}"},
                    {"name": f"Stratagem4_{role}_{enemy}"}
                ],
                "objective": f"Placeholder objective vs {enemy}",
                "lore": f"Placeholder lore for a {role} against {enemy}.",
                "loadout_name": f"{role} vs {enemy} (Placeholder)"
            }
    save_cache(cache)
    return cache

def display_cached_loadout(role, enemy):
    cache = load_json(CACHE_FILE)
    if not cache:
        cache = build_initial_cache()
    key = f"{role}_{enemy}"
    loadout = cache.get(key)
    print(f"\nCached loadout for {role} vs {enemy}:")
    print(json.dumps(loadout, indent=2))

def get_used_loadout_names(role: str = None):
    """
    Collect all loadout_name values from cache and backup JSON files.
    If `role` is provided, only names from that role are included.
    Supports both dict and [dict, bool] formats.
    """
    used_names = set()
    target_role = role.lower() if role else None

    for file in [CACHE_FILE, BACKUP_FILE]:
        if not os.path.exists(file):
            continue

        with open(file, "r", encoding="utf-8") as f:
            data = json.load(f)

        for key, entry in data.items():
            loadout = _coerce_to_loadout(entry)
            if not loadout or "loadout_name" not in loadout:
                continue

            key_role = key.split("_")[0].lower() if "_" in key else ""
            if target_role and target_role != key_role:
                continue

            used_names.add(loadout["loadout_name"])

    return used_names

def print_usage_counts(cache):
    """Shows how many times each LoadOut/stratagem is used across all 12 builds."""
    counts = Counter()
    for entry in cache.values():
        for g in entry["loadout"].values():
            counts[g["name"]] += 1
        for s in entry["stratagems"]:
            counts[s["name"]] += 1
    print("\nItem Usage Across Cache:")
    for item, cnt in counts.most_common():
        print(f"  {item}: {cnt}")

# -------------------- Loadout Validation & Filtering --------------------

def _coerce_to_loadout(obj):
    """Accepts dict, list, tuple, or None and returns the first valid loadout dict."""
    if isinstance(obj, dict) and "loadout" in obj and "stratagems" in obj:
        return obj
    if isinstance(obj, (list, tuple)):
        for item in obj:
            if isinstance(item, dict) and "loadout" in item and "stratagems" in item:
                return item
    return {}

def calculate_weight(score):
    return max(0.5, score ** 1.2)

def weighted_choice(items, count):
    selected = []
    weights = [calculate_weight(item["score"]) for item in items]

    while items and len(selected) < count:
        total_weight = sum(weights)
        if total_weight == 0:
            break
        normalized_weights = [w / total_weight for w in weights]
        picked = random.choices(items, weights=normalized_weights, k=1)[0]
        selected.append(picked)

        # Adjust weights for variety
        if picked["score"] <= 6:
            weights = [w * 1.5 if i["score"] >= 9 else w for i, w in zip(items, weights)]
        elif picked["score"] >= 9:
            weights = [w * 1.3 if 7 <= i["score"] <= 8 else w for i, w in zip(items, weights)]

        idx = items.index(picked)
        items.pop(idx)
        weights.pop(idx)

    return selected

def get_average_effectiveness(item):
    scores = []
    for key in ["automatons_effectiveness", "terminids_effectiveness", "illuminate_effectiveness"]:
        if key in item:
            try:
                scores.append(float(item[key]))
            except (ValueError, TypeError):
                continue
    return sum(scores) / len(scores) if scores else 0

def unique_candidates(pool_items, existing):
    """Filter pool items to avoid duplicate names."""
    existing_names = {s["name"] for s in existing}
    return [s for s in pool_items if s["name"] not in existing_names]

# -------------------- Role/Faction Utilities --------------------

def choose_role():
    weights = [0.35, 0.35, 0.10, 0.20]  # bias but avoid 100% CC
    return random.choices(ROLES, weights=weights, k=1)[0]

def choose_faction():
    weights = [0.36, 0.34, 0.30]  # bias distribution
    return random.choices(ENEMIES, weights=weights, k=1)[0]

