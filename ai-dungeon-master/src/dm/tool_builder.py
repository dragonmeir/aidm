"""Dynamic tool registration from a RuleSystem definition.

Builds a DMToolkit with tools appropriate for the loaded system:
- Core tools (always present): roll_dice, damage, heal, track_npc, log_event
- System-adaptive tools: attack, saving_throw, ability_check, skill_check
- System-specific tools: sanity_check, push_roll, luck_roll, etc.
"""

from __future__ import annotations

from ..systems.schema import RuleSystem, _resolve_modifier
from ..systems.loader import load_system_tables
from ..game.dice import roll, DiceResult
from ..game.generic_character import GenericCharacter
from ..game.state import GameState


def build_tool_descriptions(system: RuleSystem, tools: dict) -> str:
    """Generate tool descriptions for the system prompt based on registered tools."""
    lines = [
        "## Available Tools",
        "You can invoke game mechanics by embedding tool calls in your response.",
        'Format: [[TOOL:name:{"param": "value"}]]',
        "",
        "Tools:",
    ]

    # Core tools (always available)
    lines.append('- [[TOOL:roll_dice:{"notation": "2d6+3"}]] - Roll any dice.')

    # Attack tool — description adapts to system
    if "attack" in tools:
        atk = system.combat.attack
        if atk.method == "thac0_minus_ac":
            lines.append('- [[TOOL:attack:{"attacker": "Goblin", "target": "Grond", "attacker_thac0": 19, "target_ac": 5, "damage_die": "1d6", "attack_bonus": 0}]] - Resolve an attack (THAC0 system).')
        elif atk.method == "d20_vs_ac":
            lines.append('- [[TOOL:attack:{"attacker": "Goblin", "target": "Grond", "attack_bonus": 3, "target_ac": 15, "damage_die": "1d6"}]] - Resolve an attack (d20 + bonus vs AC).')
        elif atk.method == "percentile_skill":
            lines.append('- [[TOOL:attack:{"attacker": "Investigator", "target": "Cultist", "skill_value": 45, "damage_die": "1d6"}]] - Resolve an attack (percentile skill check).')
        elif atk.method == "dice_pool":
            lines.append('- [[TOOL:attack:{"attacker": "Scout", "target": "Orc", "pool_size": 4, "damage_die": "1d6"}]] - Resolve an attack (dice pool).')
        elif atk.method == "2d6_plus_stat":
            lines.append('- [[TOOL:attack:{"attacker": "The Chosen", "target": "Vampire", "stat_bonus": 2, "damage_die": "2d6"}]] - Resolve an attack (2d6 + stat).')
        else:
            lines.append(f'- [[TOOL:attack:{{...}}]] - Resolve an attack ({atk.method}).')

    # Ability check
    if "ability_check" in tools:
        lines.append('- [[TOOL:ability_check:{"character": "Grond", "ability": "STR", "modifier": 0}]] - Roll an ability check.')

    # Skill check
    if "skill_check" in tools:
        lines.append('- [[TOOL:skill_check:{"character": "Elara", "skill": "Spot Hidden", "modifier": 0}]] - Roll a skill check.')

    # Saving throw
    if "saving_throw" in tools:
        if system.saves:
            cats = ", ".join(c.name.lower().split("/")[0] for c in system.saves.categories)
            lines.append(f'- [[TOOL:saving_throw:{{"character": "Elara", "save_type": "{system.saves.categories[0].name.lower().split("/")[0]}"}}]] - Roll a saving throw. Types: {cats}.')
        else:
            lines.append('- [[TOOL:saving_throw:{"character": "Elara", "save_type": "general"}]] - Roll a saving throw.')

    # Combat management
    if "start_combat" in tools:
        lines.append('- [[TOOL:start_combat:{"enemies": [{"name": "Goblin", "hp": 3, "defense": 6, "attack_value": 19, "damage_die": "1d6", "morale": 7, "count": 4}]}]] - Start combat.')
    if "initiative" in tools:
        lines.append('- [[TOOL:initiative:{}]] - Re-roll initiative for new round.')
    if "morale_check" in tools:
        lines.append('- [[TOOL:morale_check:{"morale_score": 7}]] - Roll morale check.')
    if "reaction_roll" in tools:
        lines.append('- [[TOOL:reaction_roll:{"modifier": 0}]] - Roll NPC reaction.')
    if "end_combat" in tools:
        lines.append('- [[TOOL:end_combat:{}]] - End combat.')

    # Exploration tools
    if "wandering_monster" in tools:
        lines.append('- [[TOOL:wandering_monster:{"area_level": 1}]] - Check for wandering monster.')
    if "open_door" in tools:
        lines.append('- [[TOOL:open_door:{"character": "Grond"}]] - Force a stuck door.')
    if "listen" in tools:
        lines.append('- [[TOOL:listen:{"character": "Grond"}]] - Listen at door.')
    if "search" in tools:
        lines.append('- [[TOOL:search:{"character": "Elara", "area": "north wall"}]] - Search for secrets. Costs 1 turn.')
    if "surprise_check" in tools:
        lines.append('- [[TOOL:surprise_check:{}]] - Check surprise before combat.')
    if "encounter_distance" in tools:
        lines.append('- [[TOOL:encounter_distance:{"environment": "dungeon"}]] - Roll encounter distance.')

    # Character tools
    if "damage" in tools:
        lines.append('- [[TOOL:damage:{"character": "Grond", "amount": 5}]] - Apply damage to a character.')
    if "heal" in tools:
        lines.append('- [[TOOL:heal:{"character": "Grond", "amount": 3}]] - Heal a character.')
    if "cast_spell" in tools:
        lines.append('- [[TOOL:cast_spell:{"character": "Elara", "spell": "Sleep"}]] - Cast a memorized spell.')
    if "roll_treasure" in tools:
        lines.append('- [[TOOL:roll_treasure:{"quality": "average"}]] - Roll treasure. quality: poor, average, good, rich, hoard.')

    # Tracking tools
    if "track_npc" in tools:
        lines.append('- [[TOOL:track_npc:{"name": "Old Ben", "disposition": "friendly", "description": "Curio shop owner"}]] - Record an NPC.')
    if "hire_retainer" in tools:
        lines.append('- [[TOOL:hire_retainer:{"name": "Ulf", "char_class": "Fighter", "level": 1, "hp": 6, "ac": 6, "wage": 1}]] - Hire a retainer.')
    if "log_event" in tools:
        lines.append('- [[TOOL:log_event:{"event_type": "treasure", "text": "Found 200gp"}]] - Log an event.')

    # Special mechanic tools
    if "sanity_check" in tools:
        lines.append('- [[TOOL:sanity_check:{"character": "Harvey", "loss_on_fail": "1d6", "loss_on_pass": "1"}]] - Sanity check.')
    if "push_roll" in tools:
        lines.append('- [[TOOL:push_roll:{"character": "Asha", "skill": "Endurance", "pool_size": 3}]] - Push a failed roll (risk damage).')
    if "luck_roll" in tools:
        lines.append('- [[TOOL:luck_roll:{"character": "Harvey"}]] - Roll luck check (percentile under Luck stat).')
    if "resource_check" in tools:
        lines.append('- [[TOOL:resource_check:{"character": "Grond", "resource": "Sanity", "delta": -5}]] - Modify a special resource.')

    lines.extend([
        "",
        "IMPORTANT RULES:",
        "1. Use tools for ALL dice rolls. Never describe a result without rolling.",
        "2. After placing a tool call, do NOT write your own result — the system will inject the real result.",
        "3. Continue your narration after the tool call and the system will fill in the outcome.",
        "4. For combat: use start_combat first, then attack for each combatant, check morale when triggered.",
    ])

    return "\n".join(lines)


class ToolBuilder:
    """Builds system-appropriate tool handlers from a RuleSystem."""

    def __init__(self, system: RuleSystem, game_state: GameState):
        self.system = system
        self.game_state = game_state
        self._tables_data = load_system_tables(system.id)

    def build_tools(self) -> dict[str, callable]:
        """Return a dict of tool_name -> handler function."""
        tools = {}

        # Core tools (always present)
        tools["roll_dice"] = self._tool_roll_dice
        tools["damage"] = self._tool_damage
        tools["heal"] = self._tool_heal
        tools["track_npc"] = self._tool_track_npc
        tools["log_event"] = self._tool_log_event
        tools["start_combat"] = self._tool_start_combat
        tools["end_combat"] = self._tool_end_combat
        tools["initiative"] = self._tool_initiative
        tools["cast_spell"] = self._tool_cast_spell

        # Attack tool (dispatches by system)
        tools["attack"] = self._build_attack_tool()

        # Ability check
        tools["ability_check"] = self._tool_ability_check

        # Saving throw (if system has saves)
        if self.system.saves:
            tools["saving_throw"] = self._tool_saving_throw

        # Skill check (if system has skills)
        if self.system.has_skills:
            tools["skill_check"] = self._tool_skill_check

        # Reaction roll
        if self.system.reaction_table:
            tools["reaction_roll"] = self._tool_reaction_roll

        # Morale check
        if self.system.combat.morale:
            tools["morale_check"] = self._tool_morale_check

        # Exploration tools (if system has exploration rules)
        if self.system.exploration:
            tools["wandering_monster"] = self._tool_wandering_monster
            tools["surprise_check"] = self._tool_surprise_check
            tools["encounter_distance"] = self._tool_encounter_distance
            if self.system.exploration.door_mechanic:
                tools["open_door"] = self._tool_open_door
            if self.system.exploration.listen_mechanic:
                tools["listen"] = self._tool_listen
            if self.system.exploration.search_mechanic:
                tools["search"] = self._tool_search

        # Treasure
        if self._tables_data and "treasure_tables" in self._tables_data:
            tools["roll_treasure"] = self._tool_roll_treasure

        # Retainer hiring
        tools["hire_retainer"] = self._tool_hire_retainer

        # Special mechanic tools
        for mech in self.system.special_mechanics:
            if mech.name.lower() == "sanity":
                tools["sanity_check"] = self._tool_sanity_check
            elif mech.name.lower() == "luck":
                tools["luck_roll"] = self._tool_luck_roll
            elif "push" in mech.name.lower():
                tools["push_roll"] = self._tool_push_roll
            # Generic resource modification
            if mech.mechanic_type == "resource":
                tools["resource_check"] = self._tool_resource_check

        return tools

    def _find_character(self, name: str) -> GenericCharacter | None:
        name_lower = name.lower()
        for p in self.game_state.players:
            if name_lower in p.name.lower():
                return p
        return None

    # ── Core Tools ───────────────────────────────────────────

    def _tool_roll_dice(self, notation: str = "1d20", **kwargs) -> dict:
        result = roll(notation)
        return {
            "tool": "roll_dice", "success": True,
            "data": {"notation": notation, "rolls": result.rolls, "total": result.total},
            "narrative": f"Rolled {notation}",
            "mechanical": str(result),
        }

    def _tool_damage(self, character: str, amount: int, **kwargs) -> dict:
        char = self._find_character(character)
        if not char:
            return {"tool": "damage", "success": False, "narrative": f"Character '{character}' not found."}
        actual = char.take_damage(amount)
        alive = char.is_alive()
        return {
            "tool": "damage", "success": True,
            "data": {"character": char.name, "damage": actual, "hp": char.hp, "max_hp": char.max_hp, "alive": alive},
            "narrative": f"{char.name} takes {actual} damage ({char.hp}/{char.max_hp} HP)" + ("" if alive else " — DEAD!"),
            "mechanical": f"{char.name}: -{actual} HP → {char.hp}/{char.max_hp}" + (" DEAD" if not alive else ""),
        }

    def _tool_heal(self, character: str, amount: int, **kwargs) -> dict:
        char = self._find_character(character)
        if not char:
            return {"tool": "heal", "success": False, "narrative": f"Character '{character}' not found."}
        actual = char.heal(amount)
        return {
            "tool": "heal", "success": True,
            "data": {"character": char.name, "healed": actual, "hp": char.hp, "max_hp": char.max_hp},
            "narrative": f"{char.name} heals {actual} HP ({char.hp}/{char.max_hp})",
            "mechanical": f"{char.name}: +{actual} HP → {char.hp}/{char.max_hp}",
        }

    def _tool_track_npc(self, name: str, disposition: str = "neutral", description: str = "", **kwargs) -> dict:
        self.game_state.track_npc(name, disposition, description=description)
        self.game_state.log_event("npc", f"Met {name} ({disposition})")
        return {
            "tool": "track_npc", "success": True,
            "data": {"name": name, "disposition": disposition},
            "narrative": f"Noted: {name} ({disposition})",
            "mechanical": f"NPC tracked: {name} — {disposition}",
        }

    def _tool_log_event(self, event_type: str = "exploration", text: str = "", **kwargs) -> dict:
        self.game_state.log_event(event_type, text)
        return {"tool": "log_event", "success": True, "narrative": "", "mechanical": ""}

    # ── Attack Tool (System-Adaptive) ────────────────────────

    def _build_attack_tool(self):
        method = self.system.combat.attack.method

        if method == "thac0_minus_ac":
            return self._attack_thac0
        elif method == "d20_vs_ac":
            return self._attack_d20_vs_ac
        elif method == "percentile_skill":
            return self._attack_percentile
        elif method == "dice_pool":
            return self._attack_dice_pool
        elif method == "2d6_plus_stat":
            return self._attack_2d6_plus_stat
        elif method == "d20_roll_under":
            return self._attack_d20_roll_under
        else:
            return self._attack_generic

    def _attack_thac0(self, attacker: str, target: str,
                      attacker_thac0: int = 19, target_ac: int = 9,
                      damage_die: str = "1d6", attack_bonus: int = 0, **kwargs) -> dict:
        attack_roll_val = roll("1d20").total
        needed = attacker_thac0 - target_ac
        hit = (attack_roll_val + attack_bonus) >= needed
        dmg = 0
        if hit:
            dmg = max(1, roll(damage_die).total)
            tc = self._find_character(target)
            if tc:
                tc.take_damage(dmg)
        return {
            "tool": "attack", "success": True,
            "data": {"attacker": attacker, "target": target, "attack_roll": attack_roll_val,
                     "needed": needed, "hit": hit, "damage": dmg},
            "narrative": f"{attacker} {'hits' if hit else 'misses'} {target}" + (f" for {dmg} damage!" if hit else "!"),
            "mechanical": f"Attack: d20={attack_roll_val} vs needed {needed} — {'HIT' if hit else 'MISS'}" + (f", {dmg} damage" if hit else ""),
        }

    def _attack_d20_vs_ac(self, attacker: str, target: str,
                          attack_bonus: int = 0, target_ac: int = 10,
                          damage_die: str = "1d6", **kwargs) -> dict:
        attack_roll_val = roll("1d20").total
        total = attack_roll_val + attack_bonus
        hit = total >= target_ac
        dmg = 0
        if hit:
            dmg = max(1, roll(damage_die).total)
            tc = self._find_character(target)
            if tc:
                tc.take_damage(dmg)
        return {
            "tool": "attack", "success": True,
            "data": {"attacker": attacker, "target": target, "attack_roll": attack_roll_val,
                     "total": total, "target_ac": target_ac, "hit": hit, "damage": dmg},
            "narrative": f"{attacker} {'hits' if hit else 'misses'} {target}" + (f" for {dmg} damage!" if hit else "!"),
            "mechanical": f"Attack: d20={attack_roll_val}+{attack_bonus}={total} vs AC {target_ac} — {'HIT' if hit else 'MISS'}" + (f", {dmg} damage" if hit else ""),
        }

    def _attack_percentile(self, attacker: str, target: str,
                           skill_value: int = 50, damage_die: str = "1d6", **kwargs) -> dict:
        roll_val = roll("1d100").total
        hit = roll_val <= skill_value
        dmg = 0
        if hit:
            dmg = max(1, roll(damage_die).total)
            tc = self._find_character(target)
            if tc:
                tc.take_damage(dmg)
        return {
            "tool": "attack", "success": True,
            "data": {"attacker": attacker, "target": target, "roll": roll_val,
                     "skill_value": skill_value, "hit": hit, "damage": dmg},
            "narrative": f"{attacker} {'hits' if hit else 'misses'} {target}" + (f" for {dmg} damage!" if hit else "!"),
            "mechanical": f"Attack: d100={roll_val} vs skill {skill_value} — {'HIT' if hit else 'MISS'}" + (f", {dmg} damage" if hit else ""),
        }

    def _attack_dice_pool(self, attacker: str, target: str,
                          pool_size: int = 3, damage_die: str = "1d6",
                          target_successes: int = 1, **kwargs) -> dict:
        dice = [roll("1d6").total for _ in range(pool_size)]
        successes = sum(1 for d in dice if d >= 6)  # 6 = success (Year Zero default)
        hit = successes >= target_successes
        dmg = 0
        if hit:
            dmg = max(1, roll(damage_die).total)
            tc = self._find_character(target)
            if tc:
                tc.take_damage(dmg)
        return {
            "tool": "attack", "success": True,
            "data": {"attacker": attacker, "target": target, "dice": dice,
                     "successes": successes, "hit": hit, "damage": dmg},
            "narrative": f"{attacker} rolls {pool_size}d6: {dice} — {successes} successes. {'Hit' if hit else 'Miss'}!" + (f" {dmg} damage!" if hit else ""),
            "mechanical": f"Attack: {pool_size}d6={dice}, {successes} successes — {'HIT' if hit else 'MISS'}" + (f", {dmg} damage" if hit else ""),
        }

    def _attack_2d6_plus_stat(self, attacker: str, target: str,
                              stat_bonus: int = 0, damage_die: str = "2d6", **kwargs) -> dict:
        roll_val = roll("2d6").total
        total = roll_val + stat_bonus
        # PbtA-style: 10+ = strong hit, 7-9 = weak hit, 6- = miss
        if total >= 10:
            result = "strong hit"
            hit = True
        elif total >= 7:
            result = "weak hit"
            hit = True
        else:
            result = "miss"
            hit = False
        dmg = 0
        if hit:
            dmg = max(1, roll(damage_die).total)
            tc = self._find_character(target)
            if tc:
                tc.take_damage(dmg)
        return {
            "tool": "attack", "success": True,
            "data": {"attacker": attacker, "target": target, "roll": roll_val,
                     "total": total, "result": result, "hit": hit, "damage": dmg},
            "narrative": f"{attacker}: 2d6+{stat_bonus}={total} — {result}!" + (f" {dmg} damage!" if hit else ""),
            "mechanical": f"Attack: 2d6={roll_val}+{stat_bonus}={total} — {result.upper()}" + (f", {dmg} damage" if hit else ""),
        }

    def _attack_d20_roll_under(self, attacker: str, target: str,
                               skill_value: int = 10, damage_die: str = "1d6", **kwargs) -> dict:
        roll_val = roll("1d20").total
        hit = roll_val <= skill_value
        dmg = 0
        if hit:
            dmg = max(1, roll(damage_die).total)
            tc = self._find_character(target)
            if tc:
                tc.take_damage(dmg)
        return {
            "tool": "attack", "success": True,
            "data": {"attacker": attacker, "target": target, "roll": roll_val,
                     "skill_value": skill_value, "hit": hit, "damage": dmg},
            "narrative": f"{attacker} {'hits' if hit else 'misses'} {target}" + (f" for {dmg} damage!" if hit else "!"),
            "mechanical": f"Attack: d20={roll_val} vs skill {skill_value} — {'HIT' if hit else 'MISS'}" + (f", {dmg} damage" if hit else ""),
        }

    def _attack_generic(self, attacker: str, target: str,
                        damage_die: str = "1d6", **kwargs) -> dict:
        dice = self.system.combat.attack.dice
        roll_val = roll(dice).total
        hit = roll_val >= 4  # generic threshold
        dmg = 0
        if hit:
            dmg = max(1, roll(damage_die).total)
            tc = self._find_character(target)
            if tc:
                tc.take_damage(dmg)
        return {
            "tool": "attack", "success": True,
            "data": {"attacker": attacker, "target": target, "roll": roll_val, "hit": hit, "damage": dmg},
            "narrative": f"{attacker} {'hits' if hit else 'misses'} {target}" + (f" for {dmg} damage!" if hit else "!"),
            "mechanical": f"Attack: {dice}={roll_val} — {'HIT' if hit else 'MISS'}" + (f", {dmg} damage" if hit else ""),
        }

    # ── Ability / Skill Checks ───────────────────────────────

    def _tool_ability_check(self, character: str, ability: str, modifier: int = 0, **kwargs) -> dict:
        char = self._find_character(character)
        method = self.system.dice_conventions.ability_check_method

        if char:
            score = char.get_attribute(ability)
            name = char.name
        else:
            score = 10
            name = character

        if method == "d20_roll_under":
            d20 = roll("1d20").total
            target = score + modifier
            success = d20 <= target
            return {
                "tool": "ability_check", "success": True,
                "data": {"roll": d20, "target": target, "passed": success, "character": name},
                "narrative": f"{name} {'succeeds' if success else 'fails'} the {ability} check",
                "mechanical": f"d20: {d20} vs {ability} {target} — {'PASS' if success else 'FAIL'}",
            }
        elif method == "d20_roll_over":
            d20 = roll("1d20").total
            target = 10 + modifier  # DC-style
            total = d20 + (score - 10) // 2  # crude modifier
            success = total >= target
            return {
                "tool": "ability_check", "success": True,
                "data": {"roll": d20, "total": total, "target": target, "passed": success, "character": name},
                "narrative": f"{name} {'succeeds' if success else 'fails'} the {ability} check",
                "mechanical": f"d20: {d20} total {total} vs DC {target} — {'PASS' if success else 'FAIL'}",
            }
        else:
            # Generic fallback
            d20 = roll("1d20").total
            target = score + modifier
            success = d20 <= target
            return {
                "tool": "ability_check", "success": True,
                "data": {"roll": d20, "target": target, "passed": success, "character": name},
                "narrative": f"{name} {'succeeds' if success else 'fails'} the {ability} check",
                "mechanical": f"d20: {d20} vs {ability} {target} — {'PASS' if success else 'FAIL'}",
            }

    def _tool_skill_check(self, character: str, skill: str, modifier: int = 0, **kwargs) -> dict:
        char = self._find_character(character)
        name = char.name if char else character
        skill_val = char.get_skill(skill) if char else 50

        resolution = self.system.skills.resolution if self.system.skills else "percentile_roll_under"

        if resolution == "percentile_roll_under":
            d100 = roll("1d100").total
            target = skill_val + modifier
            success = d100 <= target
            return {
                "tool": "skill_check", "success": True,
                "data": {"roll": d100, "target": target, "passed": success, "character": name, "skill": skill},
                "narrative": f"{name} {'succeeds' if success else 'fails'} the {skill} check",
                "mechanical": f"d100: {d100} vs {skill} {target}% — {'PASS' if success else 'FAIL'}",
            }
        elif resolution == "d6_pool":
            pool = skill_val + modifier
            dice = [roll("1d6").total for _ in range(max(1, pool))]
            successes = sum(1 for d in dice if d >= 6)
            success = successes > 0
            return {
                "tool": "skill_check", "success": True,
                "data": {"dice": dice, "successes": successes, "passed": success, "character": name, "skill": skill},
                "narrative": f"{name}: {skill} — {successes} successes" + (" — success!" if success else " — failure!"),
                "mechanical": f"{pool}d6={dice}, {successes} successes — {'PASS' if success else 'FAIL'}",
            }
        elif resolution == "2d6_plus_stat":
            roll_val = roll("2d6").total
            total = roll_val + skill_val + modifier
            if total >= 10:
                result, success = "strong hit", True
            elif total >= 7:
                result, success = "weak hit", True
            else:
                result, success = "miss", False
            return {
                "tool": "skill_check", "success": True,
                "data": {"roll": roll_val, "total": total, "result": result, "passed": success, "character": name, "skill": skill},
                "narrative": f"{name}: {skill} — {result}!",
                "mechanical": f"2d6={roll_val}+{skill_val}={total} — {result.upper()}",
            }
        else:
            # d20 roll-under as default
            d20 = roll("1d20").total
            target = skill_val + modifier
            success = d20 <= target
            return {
                "tool": "skill_check", "success": True,
                "data": {"roll": d20, "target": target, "passed": success, "character": name, "skill": skill},
                "narrative": f"{name} {'succeeds' if success else 'fails'} the {skill} check",
                "mechanical": f"d20: {d20} vs {skill} {target} — {'PASS' if success else 'FAIL'}",
            }

    def _tool_saving_throw(self, character: str, save_type: str, **kwargs) -> dict:
        char = self._find_character(character)
        name = char.name if char else character

        if char:
            target = char.get_save(save_type)
        elif self.system.saves:
            # Use default from system
            for cat in self.system.saves.categories:
                if save_type.lower() in cat.name.lower():
                    target = cat.default_target
                    break
            else:
                target = 15
        else:
            target = 15

        roll_dice = self.system.saves.roll_dice if self.system.saves else "1d20"
        d = roll(roll_dice).total
        # Most systems: roll >= target = success
        success = d >= target

        return {
            "tool": "saving_throw", "success": True,
            "data": {"roll": d, "target": target, "passed": success, "character": name},
            "narrative": f"{name} {'saves' if success else 'fails to save'} vs {save_type}",
            "mechanical": f"{roll_dice}: {d} vs {save_type} {target} — {'SAVE' if success else 'FAIL'}",
        }

    # ── Combat Management ────────────────────────────────────

    def _tool_start_combat(self, enemies: list[dict] | None = None, **kwargs) -> dict:
        if enemies is None:
            enemies = kwargs.get("enemy", kwargs.get("monsters", kwargs.get("monster", [])))
        if isinstance(enemies, dict):
            enemies = [enemies]
        if not enemies:
            return {"tool": "start_combat", "success": False, "narrative": "No enemies specified."}

        self.game_state.in_combat = True
        enemy_names = []
        for e in enemies:
            count = e.get("count", 1)
            for i in range(count):
                name = e["name"] if count == 1 else f"{e['name']} #{i+1}"
                enemy_names.append(name)

        # Roll initiative
        init = self.system.combat.initiative
        party_init = roll(init.dice).total
        enemy_init = roll(init.dice).total

        return {
            "tool": "start_combat", "success": True,
            "data": {"party_initiative": party_init, "enemy_initiative": enemy_init,
                     "enemies": enemy_names, "party_goes_first": party_init >= enemy_init},
            "narrative": f"Combat begins! Party rolls {party_init}, enemies roll {enemy_init}.",
            "mechanical": f"Initiative: Party {party_init} vs Enemies {enemy_init}. {'Party' if party_init >= enemy_init else 'Enemies'} act first.",
        }

    def _tool_initiative(self, **kwargs) -> dict:
        init = self.system.combat.initiative
        party_init = roll(init.dice).total
        enemy_init = roll(init.dice).total
        return {
            "tool": "initiative", "success": True,
            "data": {"party_initiative": party_init, "enemy_initiative": enemy_init},
            "narrative": f"Initiative: Party {party_init}, enemies {enemy_init}.",
            "mechanical": f"Initiative: Party {party_init} vs Enemies {enemy_init}",
        }

    def _tool_end_combat(self, **kwargs) -> dict:
        self.game_state.in_combat = False
        return {"tool": "end_combat", "success": True, "narrative": "Combat ends.", "mechanical": "Combat resolved."}

    def _tool_morale_check(self, morale_score: int = 7, **kwargs) -> dict:
        morale = self.system.combat.morale
        dice = morale.dice if morale else "2d6"
        result = roll(dice).total
        holds = result <= morale_score
        return {
            "tool": "morale_check", "success": True,
            "data": {"roll": result, "morale_score": morale_score, "holds": holds},
            "narrative": f"Morale {'holds' if holds else 'breaks — they flee!'}",
            "mechanical": f"Morale: {dice}={result} vs {morale_score} — {'HOLDS' if holds else 'BREAKS'}",
        }

    def _tool_reaction_roll(self, modifier: int = 0, cha_modifier: int = 0, **kwargs) -> dict:
        mod = modifier or cha_modifier
        rt = self.system.reaction_table
        dice = rt.dice if rt else "2d6"
        d = roll(dice).total
        total = d + mod

        # Look up result
        reaction = "Neutral"
        if rt and rt.results:
            for range_str, result_text in rt.results.items():
                if "-" in range_str:
                    parts = range_str.split("-")
                    try:
                        low, high = int(parts[0]), int(parts[1])
                        if low <= total <= high:
                            reaction = result_text
                            break
                    except ValueError:
                        continue
                elif total >= 11:
                    reaction = result_text

        return {
            "tool": "reaction_roll", "success": True,
            "data": {"roll": d, "modifier": mod, "total": total, "reaction": reaction},
            "narrative": f"Reaction: {reaction}",
            "mechanical": f"Reaction: {dice}={d}{'+'+str(mod) if mod else ''} = {total} — {reaction}",
        }

    # ── Exploration Tools ────────────────────────────────────

    def _tool_wandering_monster(self, area_level: int = 1, dungeon_level: int = 1, **kwargs) -> dict:
        level = area_level or dungeon_level
        # Check: 1-in-6 by default
        check = roll("1d6").total
        appears = check == 1

        if not appears:
            return {
                "tool": "wandering_monster", "success": True,
                "data": {"appears": False},
                "narrative": "No wandering monster appears.",
                "mechanical": f"Wandering monster check: d6={check}, no encounter",
            }

        # Try to get a monster from tables
        monster = None
        if self._tables_data and "wandering_monsters" in self._tables_data:
            wm = self._tables_data["wandering_monsters"]
            level_key = str(level)
            if level_key not in wm:
                level_key = str(min(int(k) for k in wm.keys())) if wm else "1"
            if level_key in wm:
                monsters = wm[level_key]
                idx = roll(f"1d{len(monsters)}").total - 1
                monster = monsters[idx].copy()
                count_dice = monster.get("count_dice", "1d4")
                monster["count"] = roll(count_dice).total

        if monster:
            return {
                "tool": "wandering_monster", "success": True,
                "data": {"appears": True, "monster": monster},
                "narrative": f"{monster['count']} {monster['name']} appear!",
                "mechanical": f"Wandering monster: {monster['count']}x {monster['name']} (HP:{monster['hp']} Def:{monster['defense']} Atk:{monster['attack_value']} Dmg:{monster['damage']} Morale:{monster['morale']})",
            }
        else:
            return {
                "tool": "wandering_monster", "success": True,
                "data": {"appears": True, "monster": None},
                "narrative": "Something stirs in the darkness — a wandering creature approaches!",
                "mechanical": "Wandering monster check: encounter! (no table data — DM must improvise)",
            }

    def _tool_surprise_check(self, party_mod: int = 0, enemy_mod: int = 0, **kwargs) -> dict:
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

        return {
            "tool": "surprise_check", "success": True,
            "data": {"party_roll": party_roll, "enemy_roll": enemy_roll,
                     "party_surprised": party_surprised, "enemy_surprised": enemy_surprised},
            "narrative": result,
            "mechanical": f"Surprise: Party d6={party_roll}, Enemies d6={enemy_roll}",
        }

    def _tool_encounter_distance(self, environment: str = "dungeon", **kwargs) -> dict:
        if environment == "dungeon":
            d = roll("2d6").total * 10
            unit = "feet"
        else:
            d = roll("4d6").total * 10
            unit = "yards"
        return {
            "tool": "encounter_distance", "success": True,
            "data": {"distance": d, "unit": unit},
            "narrative": f"Encounter at {d} {unit}!",
            "mechanical": f"Encounter distance: {d} {unit}",
        }

    def _tool_open_door(self, character: str = "", **kwargs) -> dict:
        char = self._find_character(character)
        base = roll("1d6").total
        mod = char.get_modifier("STR", self.system) if char else 0
        success = (base + mod) <= 2
        name = char.name if char else character or "The party"
        return {
            "tool": "open_door", "success": True,
            "data": {"roll": base, "modifier": mod, "opened": success, "character": name},
            "narrative": f"{name} {'forces the door open!' if success else 'cannot budge the door.'}",
            "mechanical": f"Open door: d6={base} — {'OPEN' if success else 'STUCK'}",
        }

    def _tool_listen(self, character: str = "", **kwargs) -> dict:
        char = self._find_character(character)
        d = roll("1d6").total
        # Check for enhanced hearing (demihumans, etc.)
        threshold = 1
        if char and char.character_type in ("Dwarf", "Elf", "Halfling"):
            threshold = 2
        heard = d <= threshold
        name = char.name if char else character or "The party"
        return {
            "tool": "listen", "success": True,
            "data": {"roll": d, "threshold": threshold, "heard": heard, "character": name},
            "narrative": f"{name} {'hears something beyond the door!' if heard else 'hears nothing.'}",
            "mechanical": f"Listen: d6={d} vs {threshold} — {'HEARD' if heard else 'SILENCE'}",
        }

    def _tool_search(self, character: str = "", area: str = "10x10 area", **kwargs) -> dict:
        char = self._find_character(character)
        d = roll("1d6").total
        threshold = 1
        if char and char.character_type == "Elf":
            threshold = 2
        found = d <= threshold
        name = char.name if char else character or "The party"
        self.game_state.advance_turn()
        return {
            "tool": "search", "success": True,
            "data": {"roll": d, "threshold": threshold, "found": found, "character": name, "area": area},
            "narrative": f"{name} searches the {area}... {'and finds something hidden!' if found else 'but finds nothing.'}",
            "mechanical": f"Search: d6={d} vs {threshold} — {'FOUND' if found else 'NOTHING'} (1 turn elapsed)",
        }

    # ── Spell Tools ──────────────────────────────────────────

    def _tool_cast_spell(self, character: str, spell: str, **kwargs) -> dict:
        char = self._find_character(character)
        if not char:
            return {"tool": "cast_spell", "success": False, "narrative": f"Character '{character}' not found."}
        if char.cast_spell(spell):
            remaining = len(char.available_spells())
            self.game_state.log_event("combat", f"{char.name} casts {spell}! ({remaining} spells remaining)")
            return {
                "tool": "cast_spell", "success": True,
                "data": {"character": char.name, "spell": spell, "remaining": remaining},
                "narrative": f"{char.name} casts {spell}!",
                "mechanical": f"Spell cast: {spell} — {remaining} spell(s) remaining",
            }
        return {
            "tool": "cast_spell", "success": False,
            "data": {"character": char.name, "spell": spell},
            "narrative": f"{char.name} doesn't have {spell} memorized (or already used it)!",
            "mechanical": f"Cast failed: {spell} not available",
        }

    # ── Treasure ─────────────────────────────────────────────

    def _tool_roll_treasure(self, quality: str = "average", **kwargs) -> dict:
        if not self._tables_data or "treasure_tables" not in self._tables_data:
            return {"tool": "roll_treasure", "success": True, "data": {"treasure": {}},
                    "narrative": "No treasure found.", "mechanical": "No treasure tables loaded."}

        tables = {t["quality"]: t for t in self._tables_data["treasure_tables"]}
        table = tables.get(quality, tables.get("average", {}))

        treasure = {}
        for coin_type, dice_expr in table.get("coins", {}).items():
            if dice_expr and dice_expr != "0":
                amount = roll(dice_expr).total
                if amount > 0:
                    treasure[coin_type] = amount

        if not treasure:
            return {"tool": "roll_treasure", "success": True, "data": {"treasure": {}},
                    "narrative": "No treasure found.", "mechanical": f"Treasure ({quality}): nothing"}

        parts = [f"{v} {k}" for k, v in treasure.items()]
        desc = ", ".join(parts)
        return {
            "tool": "roll_treasure", "success": True,
            "data": {"treasure": treasure},
            "narrative": f"Found: {desc}",
            "mechanical": f"Treasure ({quality}): {desc}",
        }

    # ── Retainer ─────────────────────────────────────────────

    def _tool_hire_retainer(self, name: str, char_class: str = "Fighter",
                            level: int = 1, hp: int = 4, ac: int = 7,
                            wage: int = 1, **kwargs) -> dict:
        loyalty = roll("2d6").total
        self.game_state.hire_retainer(
            name=name, char_class=char_class, level=level,
            hp=hp, ac=ac, loyalty=loyalty, wage=wage,
        )
        return {
            "tool": "hire_retainer", "success": True,
            "data": {"name": name, "loyalty": loyalty, "wage": wage},
            "narrative": f"{name} hired! Loyalty: {loyalty}, Wage: {wage}gp/day",
            "mechanical": f"Retainer: {name} ({char_class} L{level}) HP:{hp} AC:{ac} Loyalty:{loyalty} Wage:{wage}gp/day",
        }

    # ── Special Mechanic Tools ───────────────────────────────

    def _tool_sanity_check(self, character: str, loss_on_fail: str = "1d6",
                           loss_on_pass: str = "0", **kwargs) -> dict:
        char = self._find_character(character)
        name = char.name if char else character
        san = char.get_resource("Sanity") if char else 50
        d100 = roll("1d100").total
        success = d100 <= san

        if success:
            loss = roll(loss_on_pass).total if loss_on_pass != "0" else 0
        else:
            loss = roll(loss_on_fail).total

        if char and loss > 0:
            char.modify_resource("Sanity", -loss)
            new_san = char.get_resource("Sanity")
        else:
            new_san = san - loss

        return {
            "tool": "sanity_check", "success": True,
            "data": {"roll": d100, "sanity": san, "passed": success, "loss": loss, "new_sanity": new_san},
            "narrative": f"{name} {'keeps composure' if success else 'is shaken'} (SAN: {new_san}, lost {loss})",
            "mechanical": f"Sanity: d100={d100} vs SAN {san} — {'PASS' if success else 'FAIL'}, lost {loss} SAN → {new_san}",
        }

    def _tool_luck_roll(self, character: str, **kwargs) -> dict:
        char = self._find_character(character)
        name = char.name if char else character
        luck = char.get_resource("Luck") if char else 50
        d100 = roll("1d100").total
        success = d100 <= luck
        return {
            "tool": "luck_roll", "success": True,
            "data": {"roll": d100, "luck": luck, "passed": success},
            "narrative": f"{name} is {'lucky' if success else 'unlucky'}!",
            "mechanical": f"Luck: d100={d100} vs {luck} — {'LUCKY' if success else 'UNLUCKY'}",
        }

    def _tool_push_roll(self, character: str, skill: str = "", pool_size: int = 3, **kwargs) -> dict:
        char = self._find_character(character)
        name = char.name if char else character
        dice = [roll("1d6").total for _ in range(max(1, pool_size))]
        successes = sum(1 for d in dice if d >= 6)
        ones = sum(1 for d in dice if d == 1)
        success = successes > 0
        # Ones cause damage/conditions on a push
        return {
            "tool": "push_roll", "success": True,
            "data": {"dice": dice, "successes": successes, "ones": ones, "passed": success},
            "narrative": f"{name} pushes the {skill} roll: {dice} — {successes} successes, {ones} banes!",
            "mechanical": f"Push: {pool_size}d6={dice}, {successes} successes, {ones} ones (each = 1 damage/condition)",
        }

    def _tool_resource_check(self, character: str, resource: str, delta: int = 0, **kwargs) -> dict:
        char = self._find_character(character)
        if not char:
            return {"tool": "resource_check", "success": False, "narrative": f"Character '{character}' not found."}
        old_val = char.get_resource(resource)
        new_val = char.modify_resource(resource, delta)
        return {
            "tool": "resource_check", "success": True,
            "data": {"character": char.name, "resource": resource, "old": old_val, "new": new_val, "delta": delta},
            "narrative": f"{char.name}: {resource} {old_val} → {new_val}",
            "mechanical": f"{resource}: {old_val} {'+'if delta>=0 else ''}{delta} = {new_val}",
        }
