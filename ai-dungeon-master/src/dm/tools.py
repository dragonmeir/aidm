"""DM Tool System - structured actions the AI can invoke autonomously.

The DM embeds tool calls in its responses using [[TOOL:name:args]] syntax.
These get intercepted, executed with real dice/mechanics, and the results
are injected back into the narrative.

Also includes a fallback parser for when the model describes rolls in
natural language instead of using the tool syntax.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..game.dice import roll, reaction_roll, check_morale, DiceResult
from ..game.combat import (
    Combatant, CombatState, AttackResult,
    roll_initiative, resolve_attack, check_enemy_morale,
)
from ..game.tables import (
    check_wandering_monster, roll_wandering_monster, roll_treasure,
)
from ..game.character import Character, ability_modifier
from ..game.state import GameState


# Pattern to match tool calls in LLM output: [[TOOL:name:json_args]]
TOOL_CALL_PATTERN = re.compile(
    r'\[\[TOOL:(\w+):(.*?)\]\]', re.DOTALL
)

# Pattern to strip the model's fake roll results that follow a tool call
# The model often narrates "*rolls dice* The result is 12" after a tool call
FAKE_RESULT_PATTERN = re.compile(
    r'\s*\*(?:rolls?\s+dice|rolling)\*[^.]*\.\s*',
    re.IGNORECASE
)

# Patterns for natural-language roll detection (fallback)
NATURAL_ROLL_PATTERNS = [
    # "rolls a d20", "roll 2d6", etc.
    re.compile(r'(?:rolls?\s+(?:a\s+)?)(\d*d\d+(?:[+-]\d+)?)', re.I),
    # "d20 attack roll", "2d6 morale check"
    re.compile(r'(\d*d\d+(?:[+-]\d+)?)\s+(?:attack|damage|morale|reaction|saving|check|roll)', re.I),
]


@dataclass
class ToolResult:
    """Result of a DM tool invocation."""
    tool_name: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    narrative: str = ""  # Human-readable description of what happened
    mechanical: str = ""  # Mechanical details (dice results, numbers)

    def to_dict(self) -> dict:
        return {
            "tool": self.tool_name,
            "success": self.success,
            "data": self.data,
            "narrative": self.narrative,
            "mechanical": self.mechanical,
        }


class DMToolkit:
    """All the tools the DM can invoke during play.

    Supports two modes:
    1. Legacy OSE mode: __init__ with game_state only (hardcoded tools).
    2. Generic mode: from_system() with a RuleSystem (dynamic tools from ToolBuilder).
    """

    def __init__(self, game_state: GameState):
        self.game_state = game_state
        self.combat_state: CombatState | None = None
        self._rule_system = None
        self._dynamic_tools = None
        self._tool_descriptions_override = None
        self._tools = {
            "roll_dice": self.tool_roll_dice,
            "ability_check": self.tool_ability_check,
            "saving_throw": self.tool_saving_throw,
            "attack": self.tool_attack,
            "start_combat": self.tool_start_combat,
            "initiative": self.tool_initiative,
            "morale_check": self.tool_morale_check,
            "reaction_roll": self.tool_reaction_roll,
            "wandering_monster": self.tool_wandering_monster,
            "roll_treasure": self.tool_roll_treasure,
            "damage": self.tool_damage,
            "heal": self.tool_heal,
            "end_combat": self.tool_end_combat,
            "surprise_check": self.tool_surprise_check,
            "open_door": self.tool_open_door,
            "listen": self.tool_listen,
            "cast_spell": self.tool_cast_spell,
            "track_npc": self.tool_track_npc,
            "hire_retainer": self.tool_hire_retainer,
            "log_event": self.tool_log_event,
            "search": self.tool_search,
            "encounter_distance": self.tool_encounter_distance,
        }

    @classmethod
    def from_system(cls, game_state: GameState, rule_system) -> "DMToolkit":
        """Create a toolkit with dynamic tools from a RuleSystem.

        Uses ToolBuilder to generate system-appropriate tool handlers.
        """
        from .tool_builder import ToolBuilder, build_tool_descriptions

        toolkit = cls(game_state)
        toolkit._rule_system = rule_system

        builder = ToolBuilder(rule_system, game_state)
        dynamic_tools = builder.build_tools()
        toolkit._dynamic_tools = dynamic_tools

        # Override the tools dict with dynamic tools
        toolkit._tools = {}
        for name, handler in dynamic_tools.items():
            toolkit._tools[name] = handler

        # Pre-build tool descriptions
        toolkit._tool_descriptions_override = build_tool_descriptions(rule_system, dynamic_tools)

        return toolkit

    def get_tool_descriptions(self) -> str:
        """Return tool descriptions for the system prompt."""
        if self._tool_descriptions_override:
            return self._tool_descriptions_override
        return """## Available Tools
You can invoke game mechanics by embedding tool calls in your response.
Format: [[TOOL:name:{"param": "value"}]]

Tools:
- [[TOOL:roll_dice:{"notation": "2d6+3"}]] - Roll any dice.
- [[TOOL:ability_check:{"character": "Grond", "ability": "STR", "modifier": 0}]] - Roll d20 vs ability score.
- [[TOOL:saving_throw:{"character": "Elara", "save_type": "spells"}]] - Roll a saving throw. save_type: death, wands, paralysis, breath, spells.
- [[TOOL:attack:{"attacker": "Goblin", "target": "Grond", "attacker_thac0": 19, "target_ac": 5, "damage_die": "1d6", "attack_bonus": 0}]] - Resolve an attack.
- [[TOOL:start_combat:{"enemies": [{"name": "Goblin", "hp": 3, "ac": 6, "thac0": 19, "damage_die": "1d6", "morale": 7, "count": 4}]}]] - Start combat. Auto-rolls initiative.
- [[TOOL:initiative:{}]] - Re-roll initiative for new round.
- [[TOOL:morale_check:{"morale_score": 7}]] - Roll 2d6 morale check.
- [[TOOL:reaction_roll:{"cha_modifier": 0}]] - Roll 2d6 NPC reaction.
- [[TOOL:wandering_monster:{"dungeon_level": 1}]] - Check for wandering monster.
- [[TOOL:roll_treasure:{"quality": "average"}]] - Roll treasure. quality: poor, average, good, rich, hoard.
- [[TOOL:damage:{"character": "Grond", "amount": 5}]] - Apply damage to a PC.
- [[TOOL:surprise_check:{"party_mod": 0, "enemy_mod": 0}]] - Check surprise for both sides before combat.
- [[TOOL:open_door:{"character": "Grond"}]] - Force a stuck door. d6, 1-2 = open.
- [[TOOL:listen:{"character": "Grond"}]] - Listen at door. d6, 1 = hear (demihumans 1-2).
- [[TOOL:search:{"character": "Elara", "area": "north wall"}]] - Search for secrets. d6, 1 = find (elves 1-2). Costs 1 turn.
- [[TOOL:encounter_distance:{"environment": "dungeon"}]] - Roll encounter distance when monsters appear.
- [[TOOL:cast_spell:{"character": "Elara", "spell": "Sleep"}]] - Cast a memorized spell. Marks it as used.
- [[TOOL:track_npc:{"name": "Ben Mordechai", "disposition": "friendly", "description": "Curio shop owner"}]] - Record an NPC the party meets.
- [[TOOL:hire_retainer:{"name": "Ulf", "char_class": "Fighter", "level": 1, "hp": 6, "ac": 6, "wage": 1}]] - Hire a retainer NPC.
- [[TOOL:log_event:{"event_type": "treasure", "text": "Found 200gp in the chest"}]] - Log a notable event. Types: combat, treasure, npc, exploration, death, rest.
- [[TOOL:heal:{"character": "Grond", "amount": 3}]] - Heal a PC.
- [[TOOL:end_combat:{}]] - End combat.

IMPORTANT RULES:
1. Use tools for ALL dice rolls. Never describe a result without rolling.
2. After placing a tool call, do NOT write your own result — the system will inject the real result.
3. Continue your narration after the tool call and the system will fill in the outcome.
4. For combat: use start_combat first, then attack for each combatant, check morale when triggered.
"""

    def execute(self, tool_name: str, args: dict) -> ToolResult:
        """Execute a tool by name with given arguments.

        Handles both legacy ToolResult returns and dict returns from dynamic tools.
        """
        handler = self._tools.get(tool_name)
        if not handler:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                narrative=f"Unknown tool: {tool_name}",
            )
        try:
            result = handler(**args)
        except TypeError as e:
            try:
                result = handler()
            except Exception:
                return ToolResult(
                    tool_name=tool_name,
                    success=False,
                    narrative=f"(Tool '{tool_name}' received bad arguments: {e})",
                    mechanical=f"Error: {tool_name}({args}) — {e}",
                )
        except Exception as e:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                narrative=f"(Tool error: {e})",
                mechanical=f"Error: {tool_name} — {e}",
            )

        # Convert dict returns (from dynamic tools) to ToolResult
        if isinstance(result, dict):
            return ToolResult(
                tool_name=result.get("tool", tool_name),
                success=result.get("success", True),
                data=result.get("data", {}),
                narrative=result.get("narrative", ""),
                mechanical=result.get("mechanical", ""),
            )
        return result

    def _find_character(self, name: str) -> Character | None:
        """Find a character by name (case-insensitive partial match)."""
        name_lower = name.lower()
        for p in self.game_state.players:
            if name_lower in p.name.lower():
                return p
        return None

    # ── Dice Tools ──────────────────────────────────────────

    def tool_roll_dice(self, notation: str = "1d20") -> ToolResult:
        result = roll(notation)
        return ToolResult(
            tool_name="roll_dice",
            success=True,
            data={"notation": notation, "rolls": result.rolls, "total": result.total, "modifier": result.modifier},
            narrative=f"Rolled {notation}",
            mechanical=str(result),
        )

    def tool_ability_check(self, character: str, ability: str, modifier: int = 0) -> ToolResult:
        char = self._find_character(character)
        if not char:
            d20 = roll("1d20").total
            target = 10 + modifier
            success = d20 <= target
            return ToolResult(
                tool_name="ability_check",
                success=True,
                data={"roll": d20, "target": target, "passed": success, "character": character},
                narrative=f"{character} {'succeeds' if success else 'fails'} the {ability} check",
                mechanical=f"d20: {d20} vs target {target} — {'PASS' if success else 'FAIL'}",
            )

        score = char.get_ability(ability)
        d20 = roll("1d20").total
        target = score + modifier
        success = d20 <= target
        return ToolResult(
            tool_name="ability_check",
            success=True,
            data={"roll": d20, "target": target, "ability_score": score, "passed": success, "character": character},
            narrative=f"{char.name} {'succeeds' if success else 'fails'} the {ability} check",
            mechanical=f"d20: {d20} vs {ability} {score}{'+' + str(modifier) if modifier else ''} — {'PASS' if success else 'FAIL'}",
        )

    def tool_saving_throw(self, character: str, save_type: str) -> ToolResult:
        char = self._find_character(character)
        save_map = {
            "death": "save_death", "wands": "save_wands",
            "paralysis": "save_paralysis", "breath": "save_breath",
            "spells": "save_spells",
        }
        attr = save_map.get(save_type.lower(), "save_spells")

        if not char:
            target = 14
            d20 = roll("1d20").total
            success = d20 >= target
            return ToolResult(
                tool_name="saving_throw",
                success=True,
                data={"roll": d20, "target": target, "passed": success, "character": character},
                narrative=f"{character} {'saves' if success else 'fails to save'} vs {save_type}",
                mechanical=f"d20: {d20} vs {save_type} {target} — {'SAVE' if success else 'FAIL'}",
            )

        target = getattr(char, attr)
        d20 = roll("1d20").total
        success = d20 >= target
        return ToolResult(
            tool_name="saving_throw",
            success=True,
            data={"roll": d20, "target": target, "passed": success, "character": char.name},
            narrative=f"{char.name} {'saves' if success else 'fails to save'} vs {save_type}",
            mechanical=f"d20: {d20} vs {save_type} {target} — {'SAVE' if success else 'FAIL'}",
        )

    # ── Combat Tools ────────────────────────────────────────

    def tool_attack(
        self, attacker: str, target: str,
        attacker_thac0: int = 19, target_ac: int = 9,
        damage_die: str = "1d6", attack_bonus: int = 0,
    ) -> ToolResult:
        attack_roll_val = roll("1d20").total
        needed = attacker_thac0 - target_ac
        hit = attack_roll_val >= needed

        dmg = 0
        if hit:
            dmg = max(1, roll(damage_die).total + attack_bonus)
            target_char = self._find_character(target)
            if target_char:
                target_char.take_damage(dmg)

        return ToolResult(
            tool_name="attack",
            success=True,
            data={
                "attacker": attacker, "target": target,
                "attack_roll": attack_roll_val, "needed": needed,
                "hit": hit, "damage": dmg,
            },
            narrative=f"{attacker} {'hits' if hit else 'misses'} {target}" + (f" for {dmg} damage!" if hit else "!"),
            mechanical=f"Attack: d20={attack_roll_val} vs needed {needed} — {'HIT' if hit else 'MISS'}" + (f", {dmg} damage ({damage_die}+{attack_bonus})" if hit else ""),
        )

    def tool_start_combat(self, enemies: list[dict] | None = None, **kwargs) -> ToolResult:
        # Handle various arg formats the LLM might use
        if enemies is None:
            enemies = kwargs.get("enemy", kwargs.get("monsters", kwargs.get("monster", [])))
        if isinstance(enemies, dict):
            enemies = [enemies]
        if not enemies:
            return ToolResult(
                tool_name="start_combat",
                success=False,
                narrative="No enemies specified for combat.",
                mechanical="start_combat called with no enemy data",
            )

        combat = CombatState(is_active=True)

        for p in self.game_state.players:
            if p.is_alive():
                combat.party.append(Combatant.from_character(p))

        enemy_combatants = []
        for e in enemies:
            count = e.get("count", 1)
            for i in range(count):
                name = e["name"] if count == 1 else f"{e['name']} #{i+1}"
                c = Combatant.from_monster(
                    name=name,
                    hp=e.get("hp", 4),
                    ac=e.get("ac", 7),
                    thac0=e.get("thac0", 19),
                    damage_die=e.get("damage_die", "1d6"),
                    morale=e.get("morale", 7),
                )
                combat.enemies.append(c)
                enemy_combatants.append(name)

        roll_initiative(combat)
        self.combat_state = combat
        self.game_state.in_combat = True

        party_init = combat.party[0].initiative if combat.party else 0
        enemy_init = combat.enemies[0].initiative if combat.enemies else 0

        return ToolResult(
            tool_name="start_combat",
            success=True,
            data={
                "party_initiative": party_init,
                "enemy_initiative": enemy_init,
                "enemies": enemy_combatants,
                "party_goes_first": party_init >= enemy_init,
            },
            narrative=f"Combat begins! Party rolls {party_init}, enemies roll {enemy_init}.",
            mechanical=f"Initiative: Party {party_init} vs Enemies {enemy_init}. {'Party' if party_init >= enemy_init else 'Enemies'} act first.",
        )

    def tool_initiative(self) -> ToolResult:
        if not self.combat_state:
            return ToolResult(tool_name="initiative", success=False, narrative="No active combat.")

        roll_initiative(self.combat_state)
        self.combat_state.round_num += 1

        party_init = self.combat_state.party[0].initiative if self.combat_state.party else 0
        enemy_init = self.combat_state.enemies[0].initiative if self.combat_state.enemies else 0

        return ToolResult(
            tool_name="initiative",
            success=True,
            data={"round": self.combat_state.round_num, "party_initiative": party_init, "enemy_initiative": enemy_init},
            narrative=f"Round {self.combat_state.round_num}: Party {party_init}, enemies {enemy_init}.",
            mechanical=f"Round {self.combat_state.round_num} initiative: Party {party_init} vs Enemies {enemy_init}",
        )

    def tool_morale_check(self, morale_score: int = 7) -> ToolResult:
        result = roll("2d6")
        holds = result.total <= morale_score
        return ToolResult(
            tool_name="morale_check",
            success=True,
            data={"roll": result.total, "morale_score": morale_score, "holds": holds},
            narrative=f"Morale {'holds' if holds else 'breaks — they flee!'}",
            mechanical=f"Morale: 2d6={result.total} vs {morale_score} — {'HOLDS' if holds else 'BREAKS'}",
        )

    def tool_end_combat(self) -> ToolResult:
        self.combat_state = None
        self.game_state.in_combat = False
        return ToolResult(
            tool_name="end_combat",
            success=True,
            narrative="Combat ends.",
            mechanical="Combat resolved.",
        )

    # ── Encounter Tools ─────────────────────────────────────

    def tool_reaction_roll(self, cha_modifier: int = 0) -> ToolResult:
        result_text = reaction_roll(cha_modifier)
        d = roll("2d6")
        total = d.total + cha_modifier
        return ToolResult(
            tool_name="reaction_roll",
            success=True,
            data={"roll": d.total, "modifier": cha_modifier, "total": total, "reaction": result_text},
            narrative=f"Reaction: {result_text}",
            mechanical=f"Reaction: 2d6={d.total}{'+' + str(cha_modifier) if cha_modifier else ''} = {total} — {result_text}",
        )

    def tool_wandering_monster(self, dungeon_level: int = 1) -> ToolResult:
        appears = check_wandering_monster()
        if not appears:
            return ToolResult(
                tool_name="wandering_monster",
                success=True,
                data={"appears": False},
                narrative="No wandering monster appears.",
                mechanical="Wandering monster check: no encounter (1d6 > 1)",
            )

        monster = roll_wandering_monster(dungeon_level)
        return ToolResult(
            tool_name="wandering_monster",
            success=True,
            data={"appears": True, "monster": monster},
            narrative=f"{monster['count']} {monster['name']} appear!",
            mechanical=f"Wandering monster: {monster['count']}x {monster['name']} (HP:{monster['hp']} AC:{monster['ac']} THAC0:{monster['thac0']} Dmg:{monster['damage']} Morale:{monster['morale']})",
        )

    def tool_roll_treasure(self, quality: str = "average") -> ToolResult:
        treasure = roll_treasure(quality)
        if not treasure:
            return ToolResult(
                tool_name="roll_treasure",
                success=True,
                data={"treasure": {}},
                narrative="No treasure found.",
                mechanical=f"Treasure ({quality}): nothing",
            )

        parts = [f"{v} {k}" for k, v in treasure.items()]
        desc = ", ".join(parts)
        return ToolResult(
            tool_name="roll_treasure",
            success=True,
            data={"treasure": treasure},
            narrative=f"Found: {desc}",
            mechanical=f"Treasure ({quality}): {desc}",
        )

    # ── Character Tools ─────────────────────────────────────

    def tool_damage(self, character: str, amount: int) -> ToolResult:
        char = self._find_character(character)
        if not char:
            return ToolResult(tool_name="damage", success=False, narrative=f"Character '{character}' not found.")

        actual = char.take_damage(amount)
        alive = char.is_alive()
        return ToolResult(
            tool_name="damage",
            success=True,
            data={"character": char.name, "damage": actual, "hp": char.hp, "max_hp": char.max_hp, "alive": alive},
            narrative=f"{char.name} takes {actual} damage ({char.hp}/{char.max_hp} HP)" + ("" if alive else " — DEAD!"),
            mechanical=f"{char.name}: -{actual} HP → {char.hp}/{char.max_hp}" + (" DEAD" if not alive else ""),
        )

    def tool_heal(self, character: str, amount: int) -> ToolResult:
        char = self._find_character(character)
        if not char:
            return ToolResult(tool_name="heal", success=False, narrative=f"Character '{character}' not found.")

        actual = char.heal(amount)
        return ToolResult(
            tool_name="heal",
            success=True,
            data={"character": char.name, "healed": actual, "hp": char.hp, "max_hp": char.max_hp},
            narrative=f"{char.name} heals {actual} HP ({char.hp}/{char.max_hp})",
            mechanical=f"{char.name}: +{actual} HP → {char.hp}/{char.max_hp}",
        )

    # ── Exploration Tools ───────────────────────────────────

    def tool_surprise_check(self, party_mod: int = 0, enemy_mod: int = 0) -> ToolResult:
        """Check surprise for both sides. 1-2 on d6 = surprised."""
        party_roll = roll("1d6").total
        enemy_roll = roll("1d6").total
        party_surprised = (party_roll + party_mod) <= 2
        enemy_surprised = (enemy_roll + enemy_mod) <= 2

        if party_surprised and enemy_surprised:
            result = "Both sides surprised! No one acts for 1 round."
        elif party_surprised:
            result = "Party is SURPRISED! Enemies get a free round."
        elif enemy_surprised:
            result = "Enemies are SURPRISED! Party gets a free round."
        else:
            result = "No surprise — both sides are alert."

        return ToolResult(
            tool_name="surprise_check",
            success=True,
            data={"party_roll": party_roll, "enemy_roll": enemy_roll,
                  "party_surprised": party_surprised, "enemy_surprised": enemy_surprised},
            narrative=result,
            mechanical=f"Surprise: Party d6={party_roll} {'SURPRISED' if party_surprised else 'alert'}, Enemies d6={enemy_roll} {'SURPRISED' if enemy_surprised else 'alert'}",
        )

    def tool_open_door(self, character: str = "") -> ToolResult:
        """Try to force open a stuck door. 1-2 on d6 = success (STR mod applies)."""
        char = self._find_character(character)
        base = roll("1d6").total
        mod = 0
        if char:
            mod = char.get_modifier("STR")
        success = (base + mod) <= 2

        name = char.name if char else character or "The party"
        return ToolResult(
            tool_name="open_door",
            success=True,
            data={"roll": base, "modifier": mod, "opened": success, "character": name},
            narrative=f"{name} {'forces the door open!' if success else 'cannot budge the door.'}",
            mechanical=f"Open door: d6={base}{'+'+str(mod) if mod else ''} — {'OPEN' if success else 'STUCK'}",
        )

    def tool_listen(self, character: str = "") -> ToolResult:
        """Listen at a door. 1 on d6 = hear something (demihumans 1-2)."""
        char = self._find_character(character)
        d = roll("1d6").total
        # Demihumans hear on 1-2
        is_demihuman = False
        if char:
            from ..game.character import CharacterClass
            is_demihuman = char.char_class in (CharacterClass.DWARF, CharacterClass.ELF, CharacterClass.HALFLING)
        threshold = 2 if is_demihuman else 1
        heard = d <= threshold

        name = char.name if char else character or "The party"
        return ToolResult(
            tool_name="listen",
            success=True,
            data={"roll": d, "threshold": threshold, "heard": heard, "character": name},
            narrative=f"{name} {'hears something beyond the door!' if heard else 'hears nothing.'}",
            mechanical=f"Listen: d6={d} vs {threshold} — {'HEARD' if heard else 'SILENCE'}",
        )

    def tool_search(self, character: str = "", area: str = "10x10 area") -> ToolResult:
        """Search for secret doors/hidden things. 1 on d6 (elves 1-2). Takes 1 turn."""
        char = self._find_character(character)
        d = roll("1d6").total
        is_elf = False
        if char:
            from ..game.character import CharacterClass
            is_elf = char.char_class == CharacterClass.ELF
        threshold = 2 if is_elf else 1
        found = d <= threshold

        name = char.name if char else character or "The party"
        # Advance turn since searching takes time
        self.game_state.advance_turn()

        return ToolResult(
            tool_name="search",
            success=True,
            data={"roll": d, "threshold": threshold, "found": found, "character": name, "area": area},
            narrative=f"{name} searches the {area}... {'and finds something hidden!' if found else 'but finds nothing.'}",
            mechanical=f"Search: d6={d} vs {threshold} — {'FOUND' if found else 'NOTHING'} (1 turn elapsed)",
        )

    def tool_encounter_distance(self, environment: str = "dungeon") -> ToolResult:
        """Roll encounter distance. Dungeon: 2d6x10 feet. Outdoors: 4d6x10 yards."""
        if environment == "dungeon":
            d = roll("2d6").total * 10
            unit = "feet"
        else:
            d = roll("4d6").total * 10
            unit = "yards"

        return ToolResult(
            tool_name="encounter_distance",
            success=True,
            data={"distance": d, "unit": unit, "environment": environment},
            narrative=f"Encounter at {d} {unit}!",
            mechanical=f"Encounter distance: {d} {unit}",
        )

    # ── Spell Tools ─────────────────────────────────────────

    def tool_cast_spell(self, character: str, spell: str) -> ToolResult:
        char = self._find_character(character)
        if not char:
            return ToolResult(tool_name="cast_spell", success=False, narrative=f"Character '{character}' not found.")

        if char.cast_spell(spell):
            remaining = len(char.available_spells())
            self.game_state.log_event("combat", f"{char.name} casts {spell}! ({remaining} spells remaining)")
            return ToolResult(
                tool_name="cast_spell", success=True,
                data={"character": char.name, "spell": spell, "remaining": remaining},
                narrative=f"{char.name} casts {spell}!",
                mechanical=f"Spell cast: {spell} — {remaining} spell(s) remaining",
            )
        else:
            return ToolResult(
                tool_name="cast_spell", success=False,
                data={"character": char.name, "spell": spell},
                narrative=f"{char.name} doesn't have {spell} memorized (or already used it)!",
                mechanical=f"Cast failed: {spell} not available",
            )

    # ── NPC Tracking ────────────────────────────────────────

    def tool_track_npc(self, name: str, disposition: str = "neutral",
                       description: str = "", **kwargs) -> ToolResult:
        npc = self.game_state.track_npc(name, disposition, description=description)
        self.game_state.log_event("npc", f"Met {name} ({disposition}) at {self.game_state.current_location}")
        return ToolResult(
            tool_name="track_npc", success=True,
            data={"name": name, "disposition": disposition},
            narrative=f"Noted: {name} ({disposition})",
            mechanical=f"NPC tracked: {name} — {disposition}",
        )

    # ── Retainer Hiring ─────────────────────────────────────

    def tool_hire_retainer(self, name: str, char_class: str = "Fighter",
                           level: int = 1, hp: int = 4, ac: int = 7,
                           wage: int = 1, **kwargs) -> ToolResult:
        max_r = self.game_state.max_retainers()
        current = len([r for r in self.game_state.retainers if r.is_alive()])
        if current >= max_r:
            return ToolResult(
                tool_name="hire_retainer", success=False,
                narrative=f"Cannot hire more retainers (max {max_r} based on party CHA).",
                mechanical=f"Retainer limit: {current}/{max_r}",
            )

        # Roll loyalty: 2d6 + CHA mod of hiring character
        best_cha = max((p.charisma for p in self.game_state.players), default=10)
        from ..game.character import ability_modifier
        cha_mod = ability_modifier(best_cha)
        loyalty = roll("2d6").total + cha_mod

        r = self.game_state.hire_retainer(
            name=name, char_class=char_class, level=level,
            hp=hp, ac=ac, loyalty=loyalty, wage=wage,
        )
        return ToolResult(
            tool_name="hire_retainer", success=True,
            data={"name": name, "loyalty": loyalty, "wage": wage},
            narrative=f"{name} hired! Loyalty: {loyalty}, Wage: {wage}gp/day",
            mechanical=f"Retainer: {name} ({char_class} L{level}) HP:{hp} AC:{ac} Loyalty:{loyalty} (2d6+{cha_mod}) Wage:{wage}gp/day",
        )

    # ── Journal ─────────────────────────────────────────────

    def tool_log_event(self, event_type: str = "exploration", text: str = "", **kwargs) -> ToolResult:
        self.game_state.log_event(event_type, text)
        return ToolResult(
            tool_name="log_event", success=True,
            data={"event_type": event_type, "text": text},
            narrative="",  # Don't show in narrative, it's background logging
            mechanical="",
        )


def parse_tool_calls(text: str) -> list[tuple[str, dict, int, int]]:
    """Parse tool calls from LLM output.

    Returns list of (tool_name, args_dict, start_pos, end_pos).
    """
    results = []
    for match in TOOL_CALL_PATTERN.finditer(text):
        tool_name = match.group(1)
        args_str = match.group(2).strip()
        try:
            args = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            # Try to fix common JSON issues from LLMs
            fixed = args_str.replace("'", '"')
            try:
                args = json.loads(fixed) if fixed else {}
            except json.JSONDecodeError:
                args = {}
        results.append((tool_name, args, match.start(), match.end()))
    return results


def _strip_fake_results(text: str, tool_end_pos: int) -> tuple[str, int]:
    """Strip the model's hallucinated roll results after a tool call.

    Returns (cleaned_text, chars_removed).
    """
    after = text[tool_end_pos:]

    # Strip patterns like "*rolls dice* The result is 15. " or "*rolling* It's a hit for 4 damage."
    match = FAKE_RESULT_PATTERN.match(after)
    if match:
        return text[:tool_end_pos] + after[match.end():], match.end()

    # Strip sentences that describe dice results: "The attack roll is 12.", "It's a hit for 4 damage.", etc.
    # Keep stripping consecutive result-like sentences
    stripped = after
    changed = True
    total_removed = 0
    while changed:
        changed = False
        for pat in [
            # "The attack/damage/morale roll is X."
            r'\s*(?:The )?(?:attack |damage |morale |saving |result )?(?:roll |result |check )?(?:is |was |comes up |shows )(?:a )?\d+[^.!]*[.!]\s*',
            # "It's a hit/miss" or "The goblin hits for X damage"
            r'\s*(?:It\'?s a |The \w+ )?(?:hits?|misses?|deals?|does|strikes?|fails?)\s+[^.!]*[.!]\s*',
            # "X points of damage" or "X damage"
            r'\s*\d+\s+(?:points? of )?damage[^.!]*[.!]\s*',
        ]:
            m = re.match(pat, stripped, re.I)
            if m:
                stripped = stripped[m.end():]
                total_removed += m.end()
                changed = True
                break

    if total_removed > 0:
        return text[:tool_end_pos] + stripped, total_removed

    return text, 0


def process_dm_output(text: str, toolkit: DMToolkit) -> tuple[str, list[ToolResult]]:
    """Process DM output, executing tool calls and replacing them with real results.

    Also strips the model's hallucinated results after tool calls.
    Returns (processed_text, list_of_results).
    """
    calls = parse_tool_calls(text)
    if not calls:
        return text, []

    results = []
    # Process in reverse order so positions stay valid
    processed = text
    for tool_name, args, start, end in reversed(calls):
        result = toolkit.execute(tool_name, args)
        results.insert(0, result)

        # Log the roll
        toolkit.game_state.log_roll(tool_name, result.data)

        # Strip any fake results the model wrote after this tool call
        processed, _ = _strip_fake_results(processed, end)

        # Replace the tool call with a formatted result block
        replacement = f"\n> {result.mechanical}\n"
        processed = processed[:start] + replacement + processed[end:]

    return processed, results
