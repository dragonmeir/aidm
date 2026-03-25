"""OSE combat system - initiative, attacks, morale."""

from dataclasses import dataclass, field
from .dice import roll, check_morale
from .character import Character, ability_modifier


@dataclass
class Combatant:
    name: str
    hp: int
    max_hp: int
    ac: int
    thac0: int
    damage_die: str = "1d6"
    attack_bonus: int = 0
    morale: int = 7
    is_player: bool = False
    character: Character | None = None
    initiative: int = 0

    @classmethod
    def from_character(cls, char: Character) -> "Combatant":
        return cls(
            name=char.name,
            hp=char.hp,
            max_hp=char.max_hp,
            ac=char.ac,
            thac0=char.thac0,
            attack_bonus=char.melee_attack_bonus(),
            is_player=True,
            character=char,
        )

    @classmethod
    def from_monster(cls, name: str, hp: int, ac: int, thac0: int,
                     damage_die: str = "1d6", morale: int = 7) -> "Combatant":
        return cls(
            name=name, hp=hp, max_hp=hp, ac=ac, thac0=thac0,
            damage_die=damage_die, morale=morale,
        )

    def is_alive(self) -> bool:
        return self.hp > 0


@dataclass
class AttackResult:
    attacker: str
    target: str
    attack_roll: int
    needed: int
    hit: bool
    damage: int = 0
    target_hp_remaining: int = 0

    def describe(self) -> str:
        if self.hit:
            return (
                f"{self.attacker} attacks {self.target}: "
                f"rolls {self.attack_roll} (needs {self.needed}) - HIT! "
                f"{self.damage} damage. {self.target} has {self.target_hp_remaining} HP left."
            )
        else:
            return (
                f"{self.attacker} attacks {self.target}: "
                f"rolls {self.attack_roll} (needs {self.needed}) - MISS!"
            )


@dataclass
class CombatState:
    round_num: int = 1
    party: list[Combatant] = field(default_factory=list)
    enemies: list[Combatant] = field(default_factory=list)
    initiative_order: list[Combatant] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    is_active: bool = False

    @property
    def all_combatants(self) -> list[Combatant]:
        return self.party + self.enemies

    def living_party(self) -> list[Combatant]:
        return [c for c in self.party if c.is_alive()]

    def living_enemies(self) -> list[Combatant]:
        return [c for c in self.enemies if c.is_alive()]

    def is_over(self) -> bool:
        return not self.living_party() or not self.living_enemies()


def roll_initiative(combat: CombatState) -> None:
    """Roll group initiative (OSE style: 1d6 per side)."""
    party_init = roll("1d6").total
    enemy_init = roll("1d6").total

    for c in combat.party:
        c.initiative = party_init
    for c in combat.enemies:
        c.initiative = enemy_init

    # Build initiative order (higher goes first, party wins ties)
    if party_init >= enemy_init:
        combat.initiative_order = combat.living_party() + combat.living_enemies()
    else:
        combat.initiative_order = combat.living_enemies() + combat.living_party()

    combat.log.append(
        f"Initiative: Party {party_init} vs Enemies {enemy_init}"
    )


def resolve_attack(attacker: Combatant, target: Combatant) -> AttackResult:
    """Resolve a single attack roll."""
    attack_roll = roll("1d20").total
    needed = attacker.thac0 - target.ac
    hit = attack_roll >= needed

    damage = 0
    if hit:
        damage = max(1, roll(attacker.damage_die).total + attacker.attack_bonus)
        target.hp -= damage
        if target.character:
            target.character.hp = target.hp

    return AttackResult(
        attacker=attacker.name,
        target=target.name,
        attack_roll=attack_roll,
        needed=needed,
        hit=hit,
        damage=damage,
        target_hp_remaining=max(0, target.hp),
    )


def check_enemy_morale(combat: CombatState) -> list[str]:
    """Check morale for enemies. Triggered when first enemy dies or half are down."""
    fled = []
    for enemy in combat.living_enemies():
        if not check_morale(enemy.morale):
            fled.append(enemy.name)
            enemy.hp = 0  # Remove from combat
    return fled
