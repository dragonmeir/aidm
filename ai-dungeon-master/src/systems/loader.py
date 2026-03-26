"""Load, save, and list rule system definitions from data/systems/."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from .schema import RuleSystem, EquipmentDefinitions, WeaponDefinition, ArmorDefinition

# Resolve the data/systems directory relative to the project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SYSTEMS_DIR = _PROJECT_ROOT / "data" / "systems"


def list_systems() -> list[str]:
    """Return IDs of all available rule systems (subdirectory names under data/systems/)."""
    if not SYSTEMS_DIR.is_dir():
        return []
    return sorted(
        d.name for d in SYSTEMS_DIR.iterdir()
        if d.is_dir() and (d / "system.yaml").exists()
    )


def load_system(system_id: str) -> RuleSystem:
    """Load a rule system from data/systems/<system_id>/system.yaml.

    Raises FileNotFoundError if the system directory or YAML doesn't exist.
    Raises ValueError if the YAML doesn't validate against the schema.
    """
    system_dir = SYSTEMS_DIR / system_id
    system_file = system_dir / "system.yaml"

    if not system_file.exists():
        raise FileNotFoundError(
            f"Rule system '{system_id}' not found at {system_file}"
        )

    with open(system_file, "r") as f:
        data = yaml.safe_load(f)

    try:
        system = RuleSystem.model_validate(data)
    except Exception as e:
        raise ValueError(f"Invalid rule system definition '{system_id}': {e}") from e

    # Merge equipment.yaml into the system if it exists and equipment isn't inline
    if system.equipment is None:
        equip_data = load_system_equipment(system_id)
        if equip_data:
            system.equipment = EquipmentDefinitions(
                weapons=[WeaponDefinition(**w) for w in equip_data.get("weapons", [])],
                armor=[ArmorDefinition(**a) for a in equip_data.get("armor", [])],
                currency_unit=equip_data.get("currency_unit", "gp"),
                currency_types=equip_data.get("currency_types", ["gp"]),
                starting_wealth=equip_data.get("starting_wealth", ""),
                encumbrance_unit=equip_data.get("encumbrance_unit", ""),
                encumbrance_thresholds=equip_data.get("encumbrance_thresholds", {}),
            )

    return system


def save_system(system: RuleSystem) -> Path:
    """Save a rule system to data/systems/<id>/system.yaml.

    Creates the directory if needed. Returns the path to the saved file.
    """
    system_dir = SYSTEMS_DIR / system.id
    system_dir.mkdir(parents=True, exist_ok=True)
    system_file = system_dir / "system.yaml"

    # Serialize to dict, excluding None values for cleanliness
    data = system.model_dump(exclude_none=True)

    with open(system_file, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return system_file


def load_system_tables(system_id: str) -> dict | None:
    """Load optional tables.yaml for a system (wandering monsters, treasure, etc.)."""
    tables_file = SYSTEMS_DIR / system_id / "tables.yaml"
    if not tables_file.exists():
        return None
    with open(tables_file, "r") as f:
        return yaml.safe_load(f)


def load_system_equipment(system_id: str) -> dict | None:
    """Load optional equipment.yaml for a system."""
    equip_file = SYSTEMS_DIR / system_id / "equipment.yaml"
    if not equip_file.exists():
        return None
    with open(equip_file, "r") as f:
        return yaml.safe_load(f)


def get_system_dir(system_id: str) -> Path:
    """Return the directory path for a system (may not exist yet)."""
    return SYSTEMS_DIR / system_id
