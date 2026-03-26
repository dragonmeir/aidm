"""System-aware character creation.

Uses a RuleSystem definition to roll attributes, assign class data,
calculate HP, and set up a GenericCharacter for any TTRPG.
"""

from __future__ import annotations

from ..systems.schema import RuleSystem, _resolve_modifier
from ..systems.loader import load_system_equipment
from .generic_character import GenericCharacter
from .dice import roll, roll_hp


def create_generic_character(
    name: str,
    player_name: str,
    system: RuleSystem,
    character_type: str = "",
    auto_equip: bool = True,
) -> GenericCharacter:
    """Create a new character according to the system's rules.

    Rolls attributes, applies character type data (class/playbook),
    rolls HP, and optionally equips starting gear.
    """
    char = GenericCharacter(
        name=name,
        player_name=player_name,
        system_id=system.id,
    )

    # Roll attributes
    for attr_def in system.attributes.attributes:
        method = attr_def.generation_method
        if method == "point_buy" or method == "fixed_array":
            # Default to midpoint for non-random methods
            char.attributes[attr_def.abbreviation] = (attr_def.min_value + attr_def.max_value) // 2
        else:
            # Roll dice per the generation method
            result = roll(method)
            score = max(attr_def.min_value, min(attr_def.max_value, result.total))
            char.attributes[attr_def.abbreviation] = score

    # Apply character type (class, playbook, career)
    if character_type and system.character_types:
        ct = system.get_character_type(character_type)
        if ct:
            char.character_type = ct.name

            # Saves
            char.saves = dict(ct.save_values)

            # Attack value (THAC0 or equivalent)
            if ct.thac0 is not None:
                char.attack_value = ct.thac0
                char.attack_label = "THAC0"

            # HP
            hit_die = ct.hit_die
            if hit_die:
                base_hp = roll_hp(hit_die)
                # Apply CON modifier if system has HP
                if system.health.hit_points:
                    mod_attr = system.health.hit_points.modifier_attribute
                    con_score = char.get_attribute(mod_attr)
                    attr_def = system.get_attribute_def(mod_attr)
                    if attr_def and attr_def.modifier_table:
                        con_mod = _resolve_modifier(attr_def.modifier_table, con_score)
                    else:
                        con_mod = 0
                    min_hp = system.health.hit_points.minimum_hp
                    char.max_hp = max(min_hp, base_hp + con_mod)
                else:
                    char.max_hp = max(1, base_hp)
                char.hp = char.max_hp

            # Spells
            if ct.spell_slots_by_level:
                char.spell_slots = list(ct.spell_slots_by_level)
                char.spells_known = list(ct.starting_spells)
                total_slots = sum(ct.spell_slots_by_level)
                if total_slots > 0 and ct.starting_spells:
                    char.spells_memorized = [ct.starting_spells[0]]

            # Defense base value
            if system.defense:
                char.defense_value = system.defense.base_value
                if system.defense.model == "descending_ac":
                    char.defense_label = "AC"
                elif system.defense.model == "ascending_ac":
                    char.defense_label = "AC"
                else:
                    char.defense_label = "Defense"

            # Starting equipment from character type
            if auto_equip:
                _equip_from_system(char, ct.name, system)

    elif not system.has_classes:
        # Classless system — just set up HP/defense from system defaults
        if system.health.hit_points:
            hit_die = system.health.hit_points.base_die
            base_hp = roll_hp(hit_die)
            mod_attr = system.health.hit_points.modifier_attribute
            con_score = char.get_attribute(mod_attr)
            attr_def = system.get_attribute_def(mod_attr)
            if attr_def and attr_def.modifier_table:
                con_mod = _resolve_modifier(attr_def.modifier_table, con_score)
            else:
                con_mod = 0
            char.max_hp = max(system.health.hit_points.minimum_hp, base_hp + con_mod)
            char.hp = char.max_hp

        if system.defense:
            char.defense_value = system.defense.base_value

        # Default saves
        if system.saves:
            for cat in system.saves.categories:
                char.saves[cat.name] = cat.default_target

    # Set up special resources
    for mech in system.special_mechanics:
        if mech.mechanic_type in ("resource", "condition_track"):
            # Try to compute starting value
            if mech.starting_value and mech.linked_attribute:
                attr_val = char.get_attribute(mech.linked_attribute)
                # Simple heuristic: if starting_value contains "*", multiply
                if "*" in mech.starting_value:
                    try:
                        parts = mech.starting_value.replace(mech.linked_attribute, str(attr_val))
                        parts = parts.replace("SAN", str(attr_val)).replace("POW", str(attr_val))
                        char.resources[mech.name] = int(eval(parts))
                    except Exception:
                        char.resources[mech.name] = attr_val
                else:
                    char.resources[mech.name] = attr_val
            elif mech.starting_value:
                try:
                    char.resources[mech.name] = int(mech.starting_value)
                except ValueError:
                    # Try rolling dice
                    try:
                        char.resources[mech.name] = roll(mech.starting_value).total
                    except Exception:
                        char.resources[mech.name] = 0

    # Starting wealth
    if system.equipment:
        wealth_str = system.equipment.starting_wealth
        if wealth_str:
            # Parse "3d6 * 10 gp" style
            try:
                parts = wealth_str.split()
                dice_expr = parts[0]
                multiplier = 1
                if len(parts) > 1 and parts[1] == "*":
                    multiplier = int(parts[2])
                currency = parts[-1] if len(parts) > 1 else system.equipment.currency_unit
                gold = roll(dice_expr).total * multiplier
                char.currency[currency] = gold
            except Exception:
                char.currency[system.equipment.currency_unit] = 0

    return char


def _equip_from_system(char: GenericCharacter, type_name: str, system: RuleSystem) -> None:
    """Equip starting gear from the system's equipment.yaml data."""
    equip_data = load_system_equipment(system.id)
    if not equip_data:
        return

    packages = equip_data.get("starting_packages", {})
    package = packages.get(type_name)
    if not package:
        return

    # Weapons
    for weapon_name in package.get("weapons", []):
        char.weapons.append(weapon_name)

    # Armor
    armor_name = package.get("armor")
    if armor_name:
        char.armor = armor_name
        # Look up defense value from equipment data
        for armor_def in equip_data.get("armor", []):
            if armor_def["name"] == armor_name:
                char.defense_value = armor_def["defense_value"]
                break

    # Shield
    if package.get("shield"):
        char.inventory.append("Shield")
        # In descending AC systems, shield improves (lowers) AC
        if system.defense.better_direction == "lower":
            char.defense_value -= 1
        else:
            char.defense_value += 1

    # Apply DEX modifier to defense
    if system.defense.modifier_attribute:
        dex_mod = char.get_modifier(system.defense.modifier_attribute, system)
        if system.defense.better_direction == "lower":
            char.defense_value -= dex_mod
        else:
            char.defense_value += dex_mod

    # Gear
    for item_name in package.get("gear", []):
        char.inventory.append(item_name)

    # Ammo
    for ammo_name in package.get("ammo", []):
        char.inventory.append(ammo_name)


def get_eligible_types(system: RuleSystem, attributes: dict[str, int]) -> list[str]:
    """Return which character types the given attributes qualify for."""
    if not system.character_types:
        return []

    eligible = []
    for ct in system.character_types.types:
        meets_reqs = True
        for req_attr, req_val in ct.requirements.items():
            score = attributes.get(req_attr.upper(), attributes.get(req_attr, 0))
            if score < req_val:
                meets_reqs = False
                break
        if meets_reqs:
            eligible.append(ct.name)

    return eligible
