"""OSE equipment tables, starting gear, and shop system."""

from .dice import roll
from .character import Character, CharacterClass

# ── Weapons ─────────────────────────────────────────────────

WEAPONS = {
    # name: (cost_gp, damage, weight_coins, properties)
    "Battle Axe": (7, "1d8", 50, "melee, two-handed, slow"),
    "Club": (0, "1d4", 50, "melee, blunt"),
    "Crossbow": (30, "1d6", 50, "ranged, slow, range 80/160/240"),
    "Dagger": (3, "1d4", 10, "melee, ranged, range 10/20/30"),
    "Hand Axe": (4, "1d6", 30, "melee, ranged, range 10/20/30"),
    "Holy Water": (25, "1d8", 0, "ranged, vs undead, range 10/30/50"),
    "Javelin": (1, "1d4", 20, "ranged, range 30/60/90"),
    "Lance": (5, "1d6", 120, "melee, charge"),
    "Long Bow": (40, "1d6", 30, "ranged, two-handed, range 70/140/210"),
    "Mace": (5, "1d6", 30, "melee, blunt"),
    "Morning Star": (5, "1d6", 30, "melee, blunt"),
    "Polearm": (7, "1d10", 150, "melee, two-handed, slow"),
    "Short Bow": (25, "1d6", 30, "ranged, two-handed, range 50/100/150"),
    "Short Sword": (7, "1d6", 30, "melee"),
    "Silver Dagger": (30, "1d4", 10, "melee, ranged, silver, range 10/20/30"),
    "Sling": (2, "1d4", 20, "ranged, blunt, range 40/80/160"),
    "Spear": (3, "1d6", 30, "melee, ranged, range 20/40/60"),
    "Staff": (2, "1d4", 40, "melee, two-handed, blunt"),
    "Sword": (10, "1d8", 60, "melee"),
    "Two-Handed Sword": (15, "1d10", 150, "melee, two-handed, slow"),
    "War Hammer": (5, "1d6", 30, "melee, blunt"),
}

# ── Armor ───────────────────────────────────────────────────

ARMOR = {
    # name: (cost_gp, ac, weight_coins)
    "Leather": (20, 7, 200),
    "Chain Mail": (40, 5, 400),
    "Plate Mail": (60, 3, 500),
    "Shield": (10, -1, 100),  # AC bonus (subtract from AC)
}

# ── Adventuring Gear ────────────────────────────────────────

GEAR = {
    # name: (cost_gp, weight_coins)
    "Backpack": (5, 20),
    "Crowbar": (10, 50),
    "Garlic": (5, 0),
    "Grappling Hook": (25, 80),
    "Hammer (small)": (2, 10),
    "Holy Symbol": (25, 0),
    "Iron Spikes (12)": (1, 60),
    "Lantern": (10, 30),
    "Mirror (hand-sized, steel)": (5, 10),
    "Oil (1 flask)": (2, 10),
    "Pole (10' wooden)": (1, 50),
    "Rations (standard, 7 days)": (5, 70),
    "Rations (iron, 7 days)": (15, 70),
    "Rope (50')": (1, 50),
    "Sack (small)": (1, 5),
    "Sack (large)": (2, 10),
    "Stakes (3) and Mallet": (3, 10),
    "Thieves' Tools": (25, 10),
    "Tinder Box": (3, 5),
    "Torches (6)": (1, 60),
    "Waterskin": (1, 20),
    "Wine (1 quart)": (1, 30),
    "Wolfsbane": (10, 0),
}

# ── Ammunition ──────────────────────────────────────────────

AMMO = {
    "Arrows (20)": (5, 20),
    "Crossbow Bolts (30)": (10, 30),
    "Sling Stones (20)": (0, 10),
    "Silver-tipped Arrows (5)": (25, 5),
}

# ── Starting Equipment Packages ─────────────────────────────
# Quick-start packages so characters are immediately playable.
# Each class gets a sensible default loadout.

STARTING_PACKAGES = {
    CharacterClass.FIGHTER: {
        "weapons": ["Sword", "Dagger"],
        "armor": "Chain Mail",
        "shield": True,
        "gear": ["Backpack", "Torches (6)", "Rations (standard, 7 days)", "Waterskin", "Rope (50')", "Tinder Box"],
        "ammo": [],
    },
    CharacterClass.CLERIC: {
        "weapons": ["Mace", "War Hammer"],
        "armor": "Chain Mail",
        "shield": True,
        "gear": ["Backpack", "Torches (6)", "Rations (standard, 7 days)", "Waterskin", "Holy Symbol", "Garlic", "Stakes (3) and Mallet", "Tinder Box"],
        "ammo": [],
    },
    CharacterClass.MAGIC_USER: {
        "weapons": ["Dagger", "Staff"],
        "armor": None,
        "shield": False,
        "gear": ["Backpack", "Torches (6)", "Rations (standard, 7 days)", "Waterskin", "Tinder Box", "Mirror (hand-sized, steel)", "Oil (1 flask)"],
        "ammo": [],
    },
    CharacterClass.THIEF: {
        "weapons": ["Short Sword", "Dagger", "Short Bow"],
        "armor": "Leather",
        "shield": False,
        "gear": ["Backpack", "Torches (6)", "Rations (standard, 7 days)", "Waterskin", "Thieves' Tools", "Rope (50')", "Grappling Hook", "Tinder Box"],
        "ammo": ["Arrows (20)"],
    },
    CharacterClass.DWARF: {
        "weapons": ["Battle Axe", "Hand Axe"],
        "armor": "Chain Mail",
        "shield": True,
        "gear": ["Backpack", "Torches (6)", "Rations (standard, 7 days)", "Waterskin", "Rope (50')", "Iron Spikes (12)", "Hammer (small)", "Tinder Box"],
        "ammo": [],
    },
    CharacterClass.ELF: {
        "weapons": ["Sword", "Short Bow", "Dagger"],
        "armor": "Chain Mail",
        "shield": False,
        "gear": ["Backpack", "Torches (6)", "Rations (standard, 7 days)", "Waterskin", "Rope (50')", "Tinder Box"],
        "ammo": ["Arrows (20)"],
    },
    CharacterClass.HALFLING: {
        "weapons": ["Short Sword", "Sling", "Dagger"],
        "armor": "Leather",
        "shield": True,
        "gear": ["Backpack", "Torches (6)", "Rations (standard, 7 days)", "Waterskin", "Rope (50')", "Tinder Box"],
        "ammo": ["Sling Stones (20)"],
    },
}


def equip_starting_package(char: Character) -> int:
    """Equip a character with their class's starting package.

    Deducts gold for everything. Returns total gold spent.
    If the character can't afford the full package, buys what they can.
    """
    package = STARTING_PACKAGES.get(char.char_class)
    if not package:
        return 0

    total_cost = 0

    # Calculate full package cost to see if we can afford it all
    full_cost = 0
    if package["armor"] and package["armor"] in ARMOR:
        full_cost += ARMOR[package["armor"]][0]
    if package["shield"]:
        full_cost += ARMOR["Shield"][0]
    for w in package["weapons"]:
        if w in WEAPONS:
            full_cost += WEAPONS[w][0]
    for g in package["gear"]:
        if g in GEAR:
            full_cost += GEAR[g][0]
    for a in package["ammo"]:
        if a in AMMO:
            full_cost += AMMO[a][0]

    # If can't afford everything, prioritize: weapons > gear > armor
    # Ensure everyone gets at least a weapon and basic supplies
    # Weapons first
    for weapon_name in package["weapons"]:
        if weapon_name in WEAPONS:
            cost = WEAPONS[weapon_name][0]
            if char.gold >= cost:
                char.gold -= cost
                total_cost += cost
                char.weapons.append(weapon_name)

    # Gear (essentials first)
    for item_name in package["gear"]:
        if item_name in GEAR:
            cost = GEAR[item_name][0]
            if char.gold >= cost:
                char.gold -= cost
                total_cost += cost
                char.inventory.append(item_name)

    # Ammo
    for ammo_name in package["ammo"]:
        if ammo_name in AMMO:
            cost = AMMO[ammo_name][0]
            if char.gold >= cost:
                char.gold -= cost
                total_cost += cost
                char.inventory.append(ammo_name)

    # Armor (buy best they can afford)
    if package["armor"] and package["armor"] in ARMOR:
        cost, ac, _ = ARMOR[package["armor"]]
        if char.gold >= cost:
            char.gold -= cost
            total_cost += cost
            char.armor = package["armor"]
            char.ac = ac
            if package["shield"] and char.gold >= ARMOR["Shield"][0]:
                char.gold -= ARMOR["Shield"][0]
                total_cost += ARMOR["Shield"][0]
                char.ac -= 1  # Shield improves AC by 1
                char.inventory.append("Shield")
    elif package["shield"] and char.gold >= ARMOR["Shield"][0]:
        char.gold -= ARMOR["Shield"][0]
        total_cost += ARMOR["Shield"][0]
        char.ac -= 1
        char.inventory.append("Shield")

    # Apply DEX modifier to AC
    from .character import ability_modifier
    char.ac += ability_modifier(char.dexterity)  # Note: lower AC is better, positive DEX mod helps (but OSE uses descending AC so we subtract)
    # Actually in descending AC, better DEX = lower AC number
    # Reset and recalculate properly
    base_ac = ARMOR[char.armor][1] if char.armor in ARMOR else 9
    shield_bonus = 1 if "Shield" in char.inventory else 0
    dex_mod = ability_modifier(char.dexterity)
    char.ac = base_ac - shield_bonus - dex_mod  # Descending AC: lower is better

    return total_cost


def calculate_encumbrance(char: Character) -> tuple[int, int]:
    """Calculate character's encumbrance and movement rate.

    Returns (total_weight_coins, movement_rate_feet_per_turn).
    """
    weight = 0

    # Armor weight
    if char.armor in ARMOR:
        weight += ARMOR[char.armor][2]

    # Weapons
    for w in char.weapons:
        if w in WEAPONS:
            weight += WEAPONS[w][2]

    # Gear + ammo
    for item in char.inventory:
        if item in GEAR:
            weight += GEAR[item][1]
        elif item in AMMO:
            weight += AMMO[item][1]
        elif item == "Shield":
            weight += ARMOR["Shield"][2]

    # Gold weight (10 coins = 1 lb, 1 coin ≈ 1 cn)
    weight += char.gold

    # Movement rate based on encumbrance (OSE)
    if weight <= 400:
        move = 120  # 40' per turn exploring
    elif weight <= 600:
        move = 90   # 30' per turn
    elif weight <= 800:
        move = 60   # 20' per turn
    else:
        move = 30   # 10' per turn

    return weight, move


def format_shop_listing(category: str = "all") -> str:
    """Format equipment for display."""
    lines = []

    if category in ("all", "weapons"):
        lines.append("=== WEAPONS ===")
        for name, (cost, dmg, weight, props) in sorted(WEAPONS.items()):
            lines.append(f"  {name:25s} {cost:3d} gp  {dmg:5s}  {props}")

    if category in ("all", "armor"):
        lines.append("\n=== ARMOR ===")
        for name, (cost, ac, weight) in sorted(ARMOR.items()):
            ac_str = f"AC {ac}" if ac > 0 else f"AC {ac}"
            lines.append(f"  {name:25s} {cost:3d} gp  {ac_str}")

    if category in ("all", "gear"):
        lines.append("\n=== ADVENTURING GEAR ===")
        for name, (cost, weight) in sorted(GEAR.items()):
            lines.append(f"  {name:30s} {cost:3d} gp")

    if category in ("all", "ammo"):
        lines.append("\n=== AMMUNITION ===")
        for name, (cost, weight) in sorted(AMMO.items()):
            lines.append(f"  {name:30s} {cost:3d} gp")

    return "\n".join(lines)
