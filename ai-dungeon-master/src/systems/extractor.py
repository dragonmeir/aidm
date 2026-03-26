"""LLM-powered rule extraction pipeline.

After PDFs are ingested via the existing RAG pipeline, this module
queries the LLM to extract structured rule data and populate a
RuleSystem definition for any TTRPG.

Usage:
    extractor = RuleExtractor(rag_query, ollama_client, model)
    system = extractor.extract_system(source_filter="Call of Cthulhu", system_id="coc7e")
    save_system(system)
"""

from __future__ import annotations

import json
import re
from typing import Any

import ollama

from ..rag.query import RAGQuery
from .schema import (
    RuleSystem, AttributeSystem, AttributeDefinition,
    SkillSystem, SkillDefinition,
    CharacterTypeSystem, CharacterTypeDefinition,
    CombatSystem, AttackResolution, InitiativeSystem, MoraleSystem,
    HealthSystem, HitPointConfig, DefenseSystem,
    SaveSystem, SaveCategory,
    MagicSystem, SpecialMechanic,
    DiceConventions, ExplorationRules, ReactionTable,
)
from .loader import save_system


class RuleExtractor:
    """Multi-pass extraction pipeline: RAG -> LLM -> structured RuleSystem."""

    def __init__(
        self,
        rag_query: RAGQuery,
        base_url: str = "http://localhost:11434",
        model: str = "dolphin-llama3:8b",
        context_length: int = 8192,
    ):
        self.rag = rag_query
        self.client = ollama.Client(host=base_url)
        self.model = model
        self.context_length = context_length

    def extract_system(
        self,
        source_filter: str = "",
        system_id: str = "",
        system_name: str = "",
    ) -> RuleSystem:
        """Run the full extraction pipeline.

        Args:
            source_filter: Filter RAG results to this source (e.g. "Call of Cthulhu")
            system_id: ID for the new system (e.g. "coc7e")
            system_name: Display name override

        Returns:
            A populated RuleSystem ready to save.
        """
        print(f"  [1/9] Identifying system...")
        identity = self._extract_identity(source_filter)
        sid = system_id or identity.get("id", "unknown")
        sname = system_name or identity.get("name", "Unknown System")

        print(f"  [2/9] Extracting attributes...")
        attributes = self._extract_attributes(source_filter)

        print(f"  [3/9] Extracting skills...")
        skills = self._extract_skills(source_filter)

        print(f"  [4/9] Extracting character types...")
        char_types = self._extract_character_types(source_filter)

        print(f"  [5/9] Extracting combat mechanics...")
        combat = self._extract_combat(source_filter)

        print(f"  [6/9] Extracting health & defense...")
        health, defense = self._extract_health_defense(source_filter)

        print(f"  [7/9] Extracting saving throws...")
        saves = self._extract_saves(source_filter)

        print(f"  [8/9] Extracting special mechanics...")
        specials = self._extract_special_mechanics(source_filter)

        print(f"  [9/9] Extracting magic system...")
        magic = self._extract_magic(source_filter)

        system = RuleSystem(
            id=sid,
            name=sname,
            version=identity.get("version", ""),
            genre=identity.get("genre", ""),
            attributes=attributes,
            skills=skills if skills and skills.skills else None,
            character_types=char_types if char_types and char_types.types else None,
            combat=combat,
            health=health,
            defense=defense,
            saves=saves if saves and saves.categories else None,
            magic=magic,
            special_mechanics=specials,
            dice_conventions=DiceConventions(
                primary_dice=identity.get("primary_dice", "d20"),
                stat_generation=identity.get("stat_generation", "3d6"),
                ability_check_method=identity.get("ability_check_method", "d20_roll_under"),
            ),
            dm_title=identity.get("dm_title", "Game Master"),
            player_term=identity.get("player_term", "player"),
            tone=identity.get("tone", ""),
            gm_principles=identity.get("gm_principles", []),
        )

        return system

    def _query_rag(self, queries: list[str], source_filter: str = "", top_k: int = 6) -> str:
        """Search RAG for relevant chunks across multiple queries."""
        all_chunks = []
        seen = set()
        for q in queries:
            results = self.rag.search(q, source_filter=source_filter, n_results=top_k)
            for r in results:
                text = r["text"] if isinstance(r, dict) else r
                key = text[:100]
                if key not in seen:
                    seen.add(key)
                    all_chunks.append(text)
        # Limit total context
        combined = "\n\n---\n\n".join(all_chunks[:12])
        return combined[:6000]

    def _ask_llm(self, prompt: str) -> str:
        """Send a prompt to the LLM and return the response."""
        response = self.client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            options={"temperature": 0.1, "num_ctx": self.context_length},
        )
        if isinstance(response, dict):
            return response["message"]["content"]
        return response.message.content

    def _extract_json(self, text: str) -> dict:
        """Extract a JSON object from LLM response text."""
        # Try to find JSON block
        patterns = [
            re.compile(r'```json\s*\n(.*?)\n```', re.DOTALL),
            re.compile(r'```\s*\n(.*?)\n```', re.DOTALL),
            re.compile(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', re.DOTALL),
        ]
        for pat in patterns:
            match = pat.search(text)
            if match:
                try:
                    return json.loads(match.group(1) if match.lastindex else match.group(0))
                except json.JSONDecodeError:
                    continue
        # Last resort: try the whole thing
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    # ── Extraction Passes ────────────────────────────────────

    def _extract_identity(self, source_filter: str) -> dict:
        context = self._query_rag(
            ["game system name version", "table of contents",
             "what is this RPG", "game master referee keeper"],
            source_filter, top_k=4,
        )
        prompt = f"""Based on these excerpts from a tabletop RPG rulebook, identify the system.

EXCERPTS:
{context}

Return a JSON object with these fields:
{{
    "id": "short_id_no_spaces",
    "name": "Full System Name",
    "version": "edition or version",
    "genre": "fantasy/horror/sci-fi/modern/etc",
    "primary_dice": "d20/d100/2d6/d6_pool/etc",
    "stat_generation": "3d6/2d6+6/point_buy/etc",
    "ability_check_method": "d20_roll_under/d20_roll_over/percentile_roll_under/2d6_plus_stat/dice_pool",
    "dm_title": "what the GM is called (DM/Keeper/Referee/MC/etc)",
    "player_term": "what players are called",
    "tone": "brief description of the game's tone",
    "gm_principles": ["list", "of", "GM", "guidelines"]
}}

Return ONLY the JSON, no other text."""
        return self._extract_json(self._ask_llm(prompt))

    def _extract_attributes(self, source_filter: str) -> AttributeSystem:
        context = self._query_rag(
            ["character attributes statistics ability scores",
             "strength dexterity constitution intelligence",
             "attribute generation character creation",
             "ability score modifiers bonus"],
            source_filter,
        )
        prompt = f"""Based on these RPG rulebook excerpts, extract the character attributes/statistics.

EXCERPTS:
{context}

Return a JSON object:
{{
    "generation_order": "in_order/assign/point_buy",
    "attributes": [
        {{
            "name": "Strength",
            "abbreviation": "STR",
            "min_value": 3,
            "max_value": 18,
            "generation_method": "3d6",
            "modifier_table": {{"3": -3, "4-5": -2, "6-8": -1, "9-12": 0, "13-15": 1, "16-17": 2, "18": 3}}
        }}
    ]
}}

Include ALL attributes listed in the system. If there is a modifier table, include it. If modifiers are not used, set modifier_table to null.
Return ONLY the JSON."""
        data = self._extract_json(self._ask_llm(prompt))
        attrs = []
        for a in data.get("attributes", []):
            attrs.append(AttributeDefinition(
                name=a.get("name", "Unknown"),
                abbreviation=a.get("abbreviation", a.get("name", "UNK")[:3].upper()),
                min_value=a.get("min_value", 1),
                max_value=a.get("max_value", 18),
                generation_method=a.get("generation_method", "3d6"),
                modifier_table=a.get("modifier_table"),
            ))
        if not attrs:
            attrs = [AttributeDefinition(name="Strength", abbreviation="STR")]
        return AttributeSystem(
            attributes=attrs,
            generation_order=data.get("generation_order", "in_order"),
        )

    def _extract_skills(self, source_filter: str) -> SkillSystem | None:
        context = self._query_rag(
            ["skill list skills check resolution",
             "skill percentile dice pool",
             "skill improvement advancement"],
            source_filter,
        )
        prompt = f"""Based on these RPG rulebook excerpts, extract the skill system (if any).

EXCERPTS:
{context}

If this system does NOT have skills (like basic D&D), return: {{"has_skills": false}}

If it does have skills, return:
{{
    "has_skills": true,
    "resolution": "percentile_roll_under/d6_pool/2d6_plus_stat/d20_roll_under/d20_roll_over",
    "dice": "d100/d6/2d6/d20",
    "improvement_method": "check_and_roll/xp_spend/advance_on_fail/none",
    "skills": [
        {{"name": "Spot Hidden", "base_value": "25", "linked_attribute": "INT", "category": "perception"}},
        ...
    ]
}}

List ALL skills. Return ONLY the JSON."""
        data = self._extract_json(self._ask_llm(prompt))
        if not data.get("has_skills"):
            return None
        skills = [SkillDefinition(
            name=s.get("name", ""),
            base_value=str(s.get("base_value", "0")),
            linked_attribute=s.get("linked_attribute", ""),
            category=s.get("category", ""),
        ) for s in data.get("skills", [])]
        return SkillSystem(
            resolution=data.get("resolution", "percentile_roll_under"),
            dice=data.get("dice", "d100"),
            skills=skills,
            improvement_method=data.get("improvement_method", ""),
        )

    def _extract_character_types(self, source_filter: str) -> CharacterTypeSystem | None:
        context = self._query_rag(
            ["character class playbook career archetype",
             "class abilities features hit die",
             "character creation choose class",
             "saving throws class"],
            source_filter,
        )
        prompt = f"""Based on these RPG rulebook excerpts, extract the character types (classes/playbooks/careers).

EXCERPTS:
{context}

If this is a classless system, return: {{"has_types": false}}

If it has character types, return:
{{
    "has_types": true,
    "label": "Class/Playbook/Career/Archetype",
    "optional": false,
    "types": [
        {{
            "name": "Fighter",
            "hit_die": "1d8",
            "prime_attribute": "STR",
            "requirements": {{"STR": 9}},
            "save_values": {{"Death": 12, "Wands": 13}},
            "thac0": 19,
            "special_abilities": ["Extra attack at level 5"],
            "armor_allowed": ["any"],
            "weapons_allowed": ["any"]
        }}
    ]
}}

List ALL types. Include saves if the system has per-class saves. Set thac0 only for THAC0 systems.
Return ONLY the JSON."""
        data = self._extract_json(self._ask_llm(prompt))
        if not data.get("has_types"):
            return None
        types = [CharacterTypeDefinition(
            name=t.get("name", ""),
            hit_die=t.get("hit_die", ""),
            prime_attribute=t.get("prime_attribute", ""),
            requirements=t.get("requirements", {}),
            save_values=t.get("save_values", {}),
            thac0=t.get("thac0"),
            special_abilities=t.get("special_abilities", []),
            armor_allowed=t.get("armor_allowed", []),
            weapons_allowed=t.get("weapons_allowed", []),
        ) for t in data.get("types", [])]
        return CharacterTypeSystem(
            label=data.get("label", "Class"),
            optional=data.get("optional", False),
            types=types,
        )

    def _extract_combat(self, source_filter: str) -> CombatSystem:
        context = self._query_rag(
            ["combat attack hit resolution",
             "initiative turn order",
             "damage hit points wounds",
             "morale flee surrender",
             "critical hit fumble"],
            source_filter,
        )
        prompt = f"""Based on these RPG rulebook excerpts, extract the combat mechanics.

EXCERPTS:
{context}

Return a JSON object:
{{
    "attack": {{
        "method": "thac0_minus_ac/d20_vs_ac/percentile_skill/dice_pool/2d6_plus_stat/d20_roll_under/opposed_roll",
        "dice": "1d20/d100/2d6/etc",
        "success_condition": "human readable, e.g. 'roll >= THAC0 - target AC'",
        "critical_success": "natural 20 / 01-05 / etc or empty",
        "critical_failure": "natural 1 / 96-100 / etc or empty",
        "damage_default": "1d6"
    }},
    "initiative": {{
        "method": "group_d6/individual_d20/individual_d10/dex_order/draw_cards/no_initiative",
        "dice": "1d6",
        "modifier_attribute": "DEX or empty",
        "reroll_each_round": true
    }},
    "morale": {{
        "dice": "2d6",
        "holds_on": "roll <= morale_score",
        "default_score": 7,
        "check_triggers": ["first ally killed", "half group down"]
    }},
    "special_rules": ["list of notable combat rules"]
}}

If the system has no morale, set morale to null.
Return ONLY the JSON."""
        data = self._extract_json(self._ask_llm(prompt))
        atk_data = data.get("attack", {})
        init_data = data.get("initiative", {})
        morale_data = data.get("morale")

        attack = AttackResolution(
            method=atk_data.get("method", "d20_vs_ac"),
            dice=atk_data.get("dice", "1d20"),
            success_condition=atk_data.get("success_condition", ""),
            critical_success=atk_data.get("critical_success", ""),
            critical_failure=atk_data.get("critical_failure", ""),
            damage_default=atk_data.get("damage_default", "1d6"),
        )
        initiative = InitiativeSystem(
            method=init_data.get("method", "individual_d20"),
            dice=init_data.get("dice", "1d20"),
            modifier_attribute=init_data.get("modifier_attribute", ""),
            reroll_each_round=init_data.get("reroll_each_round", True),
        )
        morale = None
        if morale_data:
            morale = MoraleSystem(
                dice=morale_data.get("dice", "2d6"),
                holds_on=morale_data.get("holds_on", "roll <= morale_score"),
                default_score=morale_data.get("default_score", 7),
                check_triggers=morale_data.get("check_triggers", []),
            )
        return CombatSystem(
            attack=attack, initiative=initiative, morale=morale,
            special_rules=data.get("special_rules", []),
        )

    def _extract_health_defense(self, source_filter: str) -> tuple[HealthSystem, DefenseSystem]:
        context = self._query_rag(
            ["hit points health wounds damage",
             "armor class defense protection",
             "death dying unconscious",
             "healing recovery rest"],
            source_filter,
        )
        prompt = f"""Based on these RPG rulebook excerpts, extract health and defense mechanics.

EXCERPTS:
{context}

Return a JSON object:
{{
    "health": {{
        "model": "hit_points/conditions/stress_tracks/wound_levels/harm_clock",
        "hit_points": {{
            "base_die": "1d8",
            "modifier_attribute": "CON",
            "minimum_hp": 1
        }},
        "conditions": [],
        "death_at": "0 HP",
        "healing": "rules text",
        "death_rules": "what happens at 0 or death threshold"
    }},
    "defense": {{
        "model": "descending_ac/ascending_ac/armor_value/dodge_roll/parry_dice/none",
        "base_value": 10,
        "better_direction": "lower/higher",
        "modifier_attribute": "DEX or empty",
        "armor_examples": {{"Leather": 7, "Chain": 5}}
    }}
}}

For condition-based systems (no HP), set hit_points to null and list conditions.
Return ONLY the JSON."""
        data = self._extract_json(self._ask_llm(prompt))
        h = data.get("health", {})
        d = data.get("defense", {})

        hp_config = None
        if h.get("hit_points"):
            hp = h["hit_points"]
            hp_config = HitPointConfig(
                base_die=hp.get("base_die", "1d8"),
                modifier_attribute=hp.get("modifier_attribute", "CON"),
                minimum_hp=hp.get("minimum_hp", 1),
            )

        health = HealthSystem(
            model=h.get("model", "hit_points"),
            hit_points=hp_config,
            conditions=h.get("conditions", []),
            death_at=h.get("death_at", "0 HP"),
            healing=h.get("healing", ""),
            death_rules=h.get("death_rules", ""),
        )
        defense = DefenseSystem(
            model=d.get("model", "ascending_ac"),
            base_value=d.get("base_value", 10),
            better_direction=d.get("better_direction", "higher"),
            modifier_attribute=d.get("modifier_attribute", ""),
            armor_examples=d.get("armor_examples", {}),
        )
        return health, defense

    def _extract_saves(self, source_filter: str) -> SaveSystem | None:
        context = self._query_rag(
            ["saving throw resistance save",
             "save vs death poison wands",
             "fortitude reflex will"],
            source_filter,
        )
        prompt = f"""Based on these RPG rulebook excerpts, extract the saving throw system.

EXCERPTS:
{context}

If the system has NO saving throws, return: {{"has_saves": false}}

If it does, return:
{{
    "has_saves": true,
    "roll_dice": "1d20/d100/etc",
    "per_class": true,
    "categories": [
        {{"name": "Death/Poison", "default_target": 14, "roll_method": "d20_roll_over"}}
    ]
}}

Return ONLY the JSON."""
        data = self._extract_json(self._ask_llm(prompt))
        if not data.get("has_saves"):
            return None
        cats = [SaveCategory(
            name=c.get("name", ""),
            default_target=c.get("default_target", 15),
            roll_method=c.get("roll_method", "d20_roll_over"),
        ) for c in data.get("categories", [])]
        return SaveSystem(
            categories=cats,
            per_class=data.get("per_class", True),
            roll_dice=data.get("roll_dice", "1d20"),
        )

    def _extract_special_mechanics(self, source_filter: str) -> list[SpecialMechanic]:
        context = self._query_rag(
            ["sanity madness insanity",
             "luck fortune fate points",
             "push roll willpower stress",
             "special unique mechanic"],
            source_filter,
        )
        prompt = f"""Based on these RPG rulebook excerpts, identify any SPECIAL or UNIQUE mechanics.

EXCERPTS:
{context}

Look for mechanics like: Sanity, Luck, Push Rolls, Willpower Points, Stress, Fortune Points, Fate, Bennies, Hero Points, Corruption, etc.

Return a JSON array (empty if none):
[
    {{
        "name": "Sanity",
        "description": "Measures mental stability when facing cosmic horror",
        "mechanic_type": "resource/roll_modifier/condition_track/meta_currency/subsystem",
        "starting_value": "POW * 5",
        "linked_attribute": "POW",
        "resolution": "d100 roll under current SAN",
        "depletion_effect": "Character goes permanently insane",
        "recovery": "Therapy, downtime, defeating the source"
    }}
]

Return ONLY the JSON array."""
        data = self._extract_json(self._ask_llm(prompt))
        if isinstance(data, dict):
            data = data.get("mechanics", data.get("special_mechanics", []))
        if not isinstance(data, list):
            return []
        return [SpecialMechanic(
            name=m.get("name", ""),
            description=m.get("description", ""),
            mechanic_type=m.get("mechanic_type", "resource"),
            starting_value=m.get("starting_value", ""),
            linked_attribute=m.get("linked_attribute", ""),
            resolution=m.get("resolution", ""),
            depletion_effect=m.get("depletion_effect", ""),
            recovery=m.get("recovery", ""),
        ) for m in data if m.get("name")]

    def _extract_magic(self, source_filter: str) -> MagicSystem | None:
        context = self._query_rag(
            ["magic spells casting spell slots",
             "sorcery wizard cleric priest",
             "powers abilities supernatural"],
            source_filter,
        )
        prompt = f"""Based on these RPG rulebook excerpts, extract the magic/spellcasting system.

EXCERPTS:
{context}

If the system has NO magic or spellcasting, return: {{"has_magic": false}}

If it does, return:
{{
    "has_magic": true,
    "model": "memorize/prepare/spontaneous/mana_points/power_points/none",
    "recovery": "full_rest/short_rest/per_scene",
    "notes": "summary of how magic works in this system"
}}

Return ONLY the JSON."""
        data = self._extract_json(self._ask_llm(prompt))
        if not data.get("has_magic"):
            return None
        return MagicSystem(
            model=data.get("model", "memorize"),
            recovery=data.get("recovery", "full_rest"),
            notes=data.get("notes", ""),
        )
