import json
import random
from OpenAIRequest import generate_helldivers_loadout, rewrite_flavor_text
import os
import re
from copy import deepcopy

from collections import Counter
import time
from utils import(
    load_json, save_cache, calculate_weight, weighted_choice,
    get_average_effectiveness,  _coerce_to_loadout, unique_candidates
)
CACHE_FILE = "../json/helldivers_cached_loadouts.json"
BACKUP_FILE = "../json/Helldivers_Backup_Classes.json"
ROLES = ["Crowd Control", "Anti-Tank", "Saboteur", "Stratagem Support"]
ENEMIES = ["automatons", "terminids", "illuminate"]

def _bump_name(name: str) -> str:
    """
    If name ends with '(N)' or '#N', increment N. Otherwise append ' (2)'.
    Examples:
      'Anti-Tank vs terminids' -> 'Anti-Tank vs terminids (2)'
      'Crowd Control (3)'      -> 'Crowd Control (4)'
      'Saboteur #5'            -> 'Saboteur #6'
    """
    if not name:
        return "Loadout (2)"
    m = re.match(r"^(.*?)(?:\s*(?:\((\d+)\)|#(\d+)))\s*$", name.strip())
    if not m:
        return f"{name} (2)"
    base, n1, n2 = m.group(1), m.group(2), m.group(3)
    n = int(n1 or n2 or "1") + 1
    # Prefer the '(N)' style for output
    return f"{base.strip()} ({n})"


def _get_existing_loadout_for(role: str, enemy: str) -> dict | None:
    """
    Returns a normalized loadout dict from cache or backup, or None.
    Handles mixed formats via _coerce_to_loadout.
    """
    cache = load_json(CACHE_FILE)
    key = f"{role}_{enemy}"
    entry = cache.get(key)
    ld = _coerce_to_loadout(entry)
    if ld:
        return deepcopy(ld)

    # fallback to backup if cache doesn't have a valid entry
    backup = load_json(BACKUP_FILE)
    entry = backup.get(key)
    ld = _coerce_to_loadout(entry)
    return deepcopy(ld) if ld else None


def filter_category(data, category, enemy_type=None, count=5):
    pool = []
    for item in data.get("loadout", []):
        if item.get("Type") == category:
            if enemy_type:
                score = float(item.get(f"{enemy_type.lower()}_effectiveness", 0))
            else:
                score = get_average_effectiveness(item)
            pool.append({
                "name": item["Name"],
                "score": score,
                "Type": item.get("Type", ""),
                "Damage Type": item.get("Damage Type", ""),
                "special_traits": item.get("special_traits", ""),
                "goal": item.get("Goal", "")
            })
    return weighted_choice(pool, count)

def filter_stratagems(data, enemy_type=None):
    pool = []
    for item in data.get("stratagems", []):
        if enemy_type:
            score = float(item.get(f"{enemy_type.lower()}_effectiveness", 0))
        else:
            score = get_average_effectiveness(item)
        pool.append({
            "name": item["name"],
            "score": score,
            "category": item.get("category", ""),
            "Damage Type": item.get("Damage Type", ""),
            "squad_role": item.get("squad_role", ""),
            "is_backpack": item.get("BackPack", "No") == "Yes",
            "is_disposable": item.get("Disposable", "No") == "Yes",
            "special_traits": item.get("special_traits", ""),
            "goal": item.get("Goal", "")
        })

    chosen = []
    support_count = 0
    backpack_count = 0

    while pool and len(chosen) < 20:
        weights = [calculate_weight(i["score"]) for i in pool]
        total_weight = sum(weights)
        normalized_weights = [w / total_weight for w in weights]
        picked = random.choices(pool, weights=normalized_weights, k=1)[0]

        if picked["category"] == "Support Weapons" and not picked["is_disposable"]:
            if support_count >= 5:
                pool.remove(picked)
                continue
            support_count += 1

        if picked["is_backpack"] and not picked["is_disposable"]:
            if backpack_count >= 5:
                pool.remove(picked)
                continue
            backpack_count += 1

        chosen.append(picked)
        pool.remove(picked)

    return chosen

def generate_filtered_pool(data, enemy_type=None):
    return {
        "primaries": filter_category(data, "Primary", enemy_type, 5),
        "secondaries": filter_category(data, "Secondary", enemy_type, 5),
        "grenades": filter_category(data, "Throwable", enemy_type, 5),
        "armor_passives": filter_category(data, "Armor Passives", enemy_type, 5),
        "stratagems": filter_stratagems(data, enemy_type)
    }

# Role selection if not provided
# --- STRATAGEM HELPERS --------------------------------------------------------
is_support = lambda s: s["category"] == "Support Weapons" and not s.get("is_disposable", False)
is_backpack = lambda s: s.get("is_backpack", False) and not s.get("is_disposable", False)

def dedupe_by_name(items):
    best = {}
    for s in items:
        if s["name"] not in best or s["score"] > best[s["name"]]["score"]:
            best[s["name"]] = s
    return list(best.values())

def trim_to_four(strats):
    """Priority order: 1 Support, 1 Backpack (if any), then top scores."""
    strats = sorted(
        strats,
        key=lambda s: (
            not is_support(s),      # keep the single Support first
            not is_backpack(s),     # keep one Backpack next
            -s["score"]             # then highest scores
        )
    )
    return strats[:4]

def check_loadout_needs_fix(loadout):
    strats = loadout.get("stratagems", [])
    names = [s["name"] for s in strats]
    duplicate = len(names) != len(set(names))

    support_cnt = sum(1 for s in strats if is_support(s))
    backpack_cnt = sum(1 for s in strats if is_backpack(s))
    four_strats  = len(strats) == 4

    # Hazard‑armor logic unchanged -------------
    items = list(loadout["loadout"].values()) + strats
    dmg_types = [i.get("Damage Type") for i in items if i.get("Damage Type")]
    counts = Counter(dmg_types)
    hazard = next((d for d, c in counts.items() if d in ["Toxic Gas", "Fire", "ARC"] and c >= 2), None)
    armor_type = loadout["loadout"].get("armor_passive", {}).get("Damage Type")
    armor_bad  = (hazard and armor_type != hazard) or (not hazard and armor_type in ["Toxic Gas", "Fire", "ARC"])

    return duplicate or support_cnt != 1 or backpack_cnt > 1 or not four_strats or armor_bad


def validate_stratagems(loadout, pool, role=None, max_passes=10):
    """
    Guarantees:
        • Exactly 4 stratagems
        • Exactly 1 non‑disposable Support Weapon
        • ≤1 non‑disposable Backpack
        • Zero duplicate names
    """
    # ---- Fill missing gear slots first --------------------------------------
    for slot, cat in [("primary", "primaries"),
                      ("secondary", "secondaries"),
                      ("grenade", "grenades"),
                      ("armor_passive", "armor_passives")]:
        if slot not in loadout["loadout"] or not loadout["loadout"][slot]:
            loadout["loadout"][slot] = max(pool[cat], key=lambda x: x["score"])

    # ---- Stabilise stratagem list -------------------------------------------
    for _ in range(max_passes):
        before = json.dumps(loadout.get("stratagems", []), sort_keys=True)
        strats = loadout.get("stratagems", [])
        strats = dedupe_by_name(strats)

        # Ensure one support
        supports = [s for s in strats if is_support(s)]
        if len(supports) != 1:
            # pick best support from pool if needed
            best_support = max(
                unique_candidates([s for s in pool["stratagems"] if is_support(s)], strats),
                key=lambda x: x["score"],
                default=None
            )
            strats = [supports[0] if supports else best_support] + [s for s in strats if not is_support(s)]

        # Enforce ≤1 backpack
        backpacks = [s for s in strats if is_backpack(s)]
        if len(backpacks) > 1:
            best_pack = max(backpacks, key=lambda x: x["score"])
            strats = [best_pack] + [s for s in strats if not is_backpack(s) or s is best_pack]

        # Top‑up with non‑support / non‑backpack picks
        while len(strats) < 4:
            candidates = unique_candidates(
                [s for s in pool["stratagems"]
                 if not is_support(s) and not is_backpack(s)], strats)
            if not candidates:
                break
            role_matches = [c for c in candidates if role and role.lower() in c.get("squad_role", "").lower()]
            pick = max(role_matches or candidates, key=lambda x: x["score"])
            if pick["name"] in {s["name"] for s in strats}:
                continue
            strats.append(pick)

        # Final trim with priority
        loadout["stratagems"] = trim_to_four(strats)

        after = json.dumps(loadout["stratagems"], sort_keys=True)
        if before == after:
            break  # stable

    return loadout


def count_item_usage(cache: dict, item_name: str, *, _max=12) -> int:
    """
    Count how many times `item_name` appears across all cached loadouts.
    Handles mixed formats (dict or [dict, flag]).
    """
    total = 0
    for entry in cache.values():
        ld = _coerce_to_loadout(entry)
        if not ld:
            continue                     # skip malformed slot

        for g in ld["loadout"].values():
            if g.get("name") == item_name:
                total += 1
        for s in ld["stratagems"]:
            if s.get("name") == item_name:
                total += 1

        if total >= _max:                # minor micro‑opt
            break
    return total
def differs_by_three_or_more(old, new):
    """Checks if the new loadout differs by at least 3 LoadOut+stratagem items."""
    old = _coerce_to_loadout(old)
    new = _coerce_to_loadout(new)
    if not old:
        return True  # No old loadout to compare
    diff_count = sum(
        1 for k in ["primary", "secondary", "grenade", "armor_passive"]
        if old["loadout"].get(k, {}).get("name") != new["loadout"].get(k, {}).get("name")
    ) + sum(
        1 for s1, s2 in zip(old["stratagems"], new["stratagems"])
        if s1.get("name") != s2.get("name")
    )
    return diff_count >= 3

def replace_overused_items(loadout, pool, cache, role, max_dupes=3):
    """
    Replaces any item over the dup‑cap with a new one,
    **never** introducing duplicate names.
    """
    # ------- helper
    def pick_best(candidates, role_key):
        role_matches = [c for c in candidates if role.lower() in c.get(role_key, "").lower()]
        return max(role_matches or candidates, key=lambda x: x["score"])

    # ------- gear slots
    existing_names = {g["name"] for g in loadout["loadout"].values()}
    for slot, g in loadout["loadout"].items():
        if count_item_usage(cache, g["name"]) >= max_dupes:
            cat = {
                "primary": "primaries",
                "secondary": "secondaries",
                "grenade": "grenades",
                "armor_passive": "armor_passives"
            }[slot]
            candidates = [i for i in pool[cat]
                          if i["name"] != g["name"] and i["name"] not in existing_names]
            if candidates:
                repl = pick_best(candidates, "goal")
                loadout["loadout"][slot] = repl
                existing_names.add(repl["name"])

    # ------- stratagems
    existing_names.update(s["name"] for s in loadout["stratagems"])
    for idx, s in enumerate(loadout["stratagems"]):
        if count_item_usage(cache, s["name"]) >= max_dupes:
            candidates = [i for i in pool["stratagems"]
                          if i["name"] != s["name"] and i["name"] not in existing_names]
            if candidates:
                repl = pick_best(candidates, "squad_role")
                loadout["stratagems"][idx] = repl
                existing_names.add(repl["name"])

    # ------- final safety: run validator once more
    return validate_stratagems(loadout, pool, role)

def update_cached_loadout(role, enemy, helldivers_data, reroll_limit=5):
    """Generates, cleans, and saves a new loadout for the given role+enemy."""

    #cache = load_json(CACHE_FILE)
    #key = f"{role}_{enemy}"

    #base_ld = _get_existing_loadout_for(role, enemy)
    #if not base_ld:
        # Nothing to bump; create a minimal placeholder so UI still renders
        #base_ld = {
            #"loadout_name": f"{role} vs {enemy} (2)",
            #"loadout": {
                #"primary": {"name": "Placeholder Primary"},
                #"secondary": {"name": "Placeholder Secondary"},
                #"grenade": {"name": "Placeholder Grenade"},
                #"armor_passive": {"name": "Placeholder Armor"},
            #},
            #"stratagems": [
                #{"name": "Placeholder Strat 1"},
                #{"name": "Placeholder Strat 2"},
                #{"name": "Placeholder Strat 3"},
                #{"name": "Placeholder Strat 4"},
            #],
            #"how_to_play": {"solo": "Test mode: no content."},
            #"objective": "Test mode objective.",
            #"lore": "Test mode lore.",
        #}
    #else:
        # bump existing name
        #current_name = base_ld.get("loadout_name") or f"{role} vs {enemy}"
        #base_ld["loadout_name"] = _bump_name(current_name)

        # Ensure role/enemy fields are present for your frontend convenience
    #base_ld.setdefault("role", role)
    #base_ld.setdefault("enemy", enemy)

    #cache[key] = base_ld
    #wait_seconds = random.randint(30, 120)
    #print(f"[DEBUG] Artificial wait {wait_seconds}s before updating cache for {role}_{enemy}")
    #time.sleep(wait_seconds)
    #save_cache(cache)
    #return base_ld

    # ---------- /TEST MODE ----------

    # ---------- ORIGINAL LOGIC BELOW ----------

    cache = load_json(CACHE_FILE)
    pool = generate_filtered_pool(helldivers_data, enemy)
    old_loadout = cache.get(f"{role}_{enemy}")

    for attempt in range(reroll_limit):
        new_loadout = generate_helldivers_loadout(pool, role=role)

        # Enforce 3-difference rule
        if not differs_by_three_or_more(old_loadout, new_loadout):
            continue

        # Enforce stratagem rules
        if check_loadout_needs_fix(new_loadout):
            new_loadout = validate_stratagems(new_loadout, pool, role=role)

        # Replace overused items (LoadOut + stratagems)
        new_loadout = replace_overused_items(new_loadout, pool, cache, role)

        # After fixes, ensure it still has 4 stratagems and passes rules
        if check_loadout_needs_fix(new_loadout):
            new_loadout = validate_stratagems(new_loadout, pool, role=role)

        # Passed all checks
        final_output = rewrite_flavor_text(new_loadout, role=role, enemy=enemy)
        cache[f"{role}_{enemy}"] = final_output
        save_cache(cache)
        return final_output

    # If no valid build after rerolls, fall back to last attempt (even if not perfect)
    final_output = rewrite_flavor_text(new_loadout, role=role, enemy=enemy)
    cache[f"{role}_{enemy}"] = final_output
    save_cache(cache)
    return final_output



