import json
import random
# Initialize API client
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # loads backend/.env into process env

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("OPENAI_API_KEY is not set")

client = api_key

from utils import get_used_loadout_names
import json
import re

def safe_json_parse(raw: str):
    """
    Returns (data, ok)
        • data – parsed dict/list or {}
        • ok   – True if a valid JSON block was found, else False
    """

    cleaned = raw.strip()

    # Chop leading / trailing code-fence noise
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9]*\n?", "", cleaned)  # remove opening ```lang
        cleaned = cleaned.rstrip("`")                          # remove trailing backticks

    # Fast path
    try:
        return json.loads(cleaned), True
    except json.JSONDecodeError:
        pass

    # Salvage path – search for first balanced JSON object or array
    for open_char, close_char in (("{", "}"), ("[", "]")):
        start = cleaned.find(open_char)
        if start == -1:
            continue

        depth = 0
        for idx, ch in enumerate(cleaned[start:], start=start):
            if ch == open_char:
                depth += 1
            elif ch == close_char:
                depth -= 1
                if depth == 0:                       # balanced block found
                    candidate = cleaned[start:idx+1]
                    try:
                        return json.loads(candidate), True
                    except json.JSONDecodeError:
                        # keep scanning – maybe the next closing brace pairs correctly
                        continue

    print("⚠️  GPT returned bad JSON that could not be salvaged.")
    return {}, False



def generate_helldivers_loadout(pool, role, max_gpt_retries=3):
    """
    Uses GPT to pick a full Helldivers 2 loadout (gear + stratagems) from the filtered pool,
    focusing purely on selecting items based on role and traits. No lore or flavor text yet.
    """
    prompt = f"""
    You are selecting a Helldivers 2 loadout for the role: {role if role else "Random"}.
    Roles:
        - Crowd Control: Focus on stuns, slowing effects, area denial, and killing swarms.
        - Anti-Tank: Specializes in elite and heavily armored enemies; uses high-penetration or heavy explosives.
        - Saboteur: Excels at destroying enemy structures, nests, and defenses; focuses on demolition tools and precision explosives.
        - Stratagem Support: Provides versatile battlefield control with sentries, orbitals, shields, and utilities (not pure DPS).
    Choose:
    - 1 Primary weapon
    - 1 Secondary weapon
    - 1 Grenade
    - 1 Armor Passive
    - 4 Stratagems (exactly 1 Support Weapon, max 1 Backpack unless disposable like EAT-17)

    Rules:
        - Always select 1 Primary, 1 Secondary, 1 Grenade, 1 Armor Passive.
        - Always select exactly 4 Stratagems.
          - Exactly 1 Support Weapon (unless it is marked "is_disposable": true, e.g., EAT-17).
          - Disposable stratagems (marked "is_disposable": true) do not count toward the Support or Backpack limits.
          - Max 1 Backpack (unless disposable).
          - Remaining 3 Stratagems must be non-Support, non-Backpack (Orbital, Sentry, Eagle, Emplacement, Mine, Vehicle).
          - Avoid duplicates unless no alternatives remain.
        - Bias toward items whose "Goal", "special_traits", or "squad_role" align with the role ({role}).
        - Within those, prioritize higher "score", but do not pick only the highest scores; ensure variety (include at least one item scoring 7 or lower when possible).
        - Stratagem mix must support the chosen role:
          - **Crowd Control**: Area denial (gas, fire), stuns, or wide-coverage weapons.
          - **Anti-Tank**: High-penetration, explosive, or anti-armor weapons and support tools.
          - **Saboteur**: Explosives for structures, hives, and defenses (Orbital artillery, Hellbomb, Thermite).
          - **Stratagem Support**: Versatile utilities (sentries, orbitals, shields) to help the team, not just DPS.
        - Always pull names only from the provided pool. Do not invent gear or stratagems.
        - Do NOT add lore, explanations, or descriptions — only return the JSON.


    Here is your filtered pool of items to choose from:
    {json.dumps(pool, indent=2)}

    Respond ONLY with a JSON object like this (no explanations):
    {{
  "loadout": {{
    "primary": {{"name": "...", "category": "Primary"}},
    "secondary": {{"name": "...", "category": "Secondary"}},
    "grenade": {{"name": "...", "category": "Throwable"}},
    "armor_passive": {{"name": "...", "category": "Armor Passive"}}
  }},
    "stratagems": [
    {{"name": "...", "category": "Support Weapons"}},
    {{"name": "...", "category": "Non-Support"}},
    {{"name": "...", "category": "Non-Support"}},
    {{"name": "...", "category": "Non-Support"}}
    ]
    }}
    Do not add explanations or lore, just select names from this pool:
    Primaries: {[g['name'] for g in pool['primaries']]}
    Secondaries: {[g['name'] for g in pool['secondaries']]}
    Grenades: {[g['name'] for g in pool['grenades']]}
    Armor Passives: {[g['name'] for g in pool['armor_passives']]}
    Stratagems: {[g['name'] for g in pool['stratagems']]}
    """

    # Send to GPT
    for attempt in range(max_gpt_retries):
        response = client.chat.completions.create(
            model="gpt-4-turbo",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        raw_content = response.choices[0].message.content.strip()
        parsed, ok = safe_json_parse(raw_content)

        if ok:  # ✅ got clean JSON – enrich & return
            return extract_selected_items(pool, parsed)

        print(f"Bad JSON (try {attempt + 1}/{max_gpt_retries}).  Retrying…")

        # All GPT attempts failed – fall back to local builder so code never crashes
    return [parsed, False]

    # All GPT attempts failed – fall back to local builder so code never crashes



def extract_selected_items(pool, selected_json):
    """
    Rebuilds a full JSON with stats & metadata for the GPT-selected names.
    """
    final_json = {"loadout": {}, "stratagems": []}

    # Match gear categories (Primary, Secondary, Grenade, Armor Passive)
    for gear_key, category_name in [
        ("primary", "primaries"),
        ("secondary", "secondaries"),
        ("grenade", "grenades"),
        ("armor_passive", "armor_passives")
    ]:
        name = selected_json["loadout"][gear_key]["name"]
        match = next((g for g in pool[category_name] if g["name"] == name), None)
        if match:
            final_json["loadout"][gear_key] = match

    # Match stratagems
    for s in selected_json["stratagems"]:
        name = s["name"]
        match = next((g for g in pool["stratagems"] if g["name"] == name), None)
        if match:
            final_json["stratagems"].append(match)

    return final_json


def rewrite_flavor_text(validated_loadout, role=None, enemy=None):
    """
    Uses GPT to rewrite flavor text (how-to-play, objective, lore, name)
    for a *fixed* loadout. Gear and stratagems remain unchanged.
    """

    gear_json = json.dumps(validated_loadout.get("loadout", {}), indent=2)
    stratagems_json = json.dumps(validated_loadout.get("stratagems", []), indent=2)

    # NEW: Collect all existing names to avoid repeats
    used_names = sorted(get_used_loadout_names())

    # Build the GPT prompt
    prompt = f"""
    You are optimizing a Helldivers 2 loadout. The loadout’s gear and stratagems are **locked** — do not rename, replace, or remove them.

    Roles:
    - Crowd Control: Focus on stuns, slowing effects, area denial, and killing swarms.
    - Anti-Tank: Specializes in elite and heavily armored enemies; uses high-penetration or heavy explosives.
    - Saboteur: Excels at destroying enemy structures, nests, and defenses; focuses on demolition tools and precision explosives.
    - Stratagem Support: Provides versatile battlefield control with sentries, orbitals, shields, and utilities (not pure DPS).

    Role: {role or "Unknown"}
    Enemy: {enemy or "Unknown"}

    Gear:
    {gear_json}

    Stratagems:
    {stratagems_json}

    Task:
    1. "how_to_play" (solo, co-op, positioning, combo flow).
    2. "objective" (1–2 concise sentences, role-appropriate).
    3. "lore" (2–3 immersive sentences reflecting the role and enemy).
    4. "loadout_name":
       - Distinctive, militaristic codename/callsign.
       - Avoids generic or overused titles (no repeated "Vanguard", "Arsenal", "Warden"). 
       - Feels like a distinctive codename or callsign, fitting the role and enemy (e.g., "Specter of Ash," "Hivebreaker Protocol").
       - 2–4 words, Title Case, no punctuation except one optional hyphen.
       - Must contain one vivid verb or adjective (e.g. “Crushing, Searing, Phantom”).
       - Must contain one concrete noun (e.g. “Hammer, Shroud, Phalanx”).
       - Skip filler words: “of, the, and, strike, fury, assault, ops, operation, protocol”.
       - Total length ≤ 22 characters (spaces excluded)..
       - Avoid any word already used in an existing loadout name : {used_names[:30]}{"..." if len(used_names) > 30 else ""}
       - No exact repeats of previous names; if collision detected, append a unique Roman numeral (II, III, IV).

    Requirements:
    - Do NOT alter the gear or stratagem lists.
    - Match the tone to the Helldivers universe.
    - Output must be valid JSON only — no commentary.

    Respond ONLY in this structure:
    {{
      "loadout": {gear_json},
      "stratagems": {stratagems_json},
      "how_to_play": {{
        "solo": "...",
        "co_op": "...",
        "positioning": "...",
        "combo_flow": "..."
      }},
      "objective": "...",
      "lore": "...",
      "loadout_name": "..."
    }}
    """

    response = client.chat.completions.create(
        model="gpt-4-turbo",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        temperature=0.85,  # slightly higher to encourage creative names
        max_tokens=1500
    )

    raw_content = response.choices[0].message.content.strip()
    selected_json, _ = safe_json_parse(raw_content)
    return selected_json
# Example Usage:
# Assuming `filtered_pool` is the output from your filtering script:
# final_loadout = generate_helldivers_loadout(filtered_pool, role="Crowd Control", enemy="Automatons")
# print(final_loadout)
