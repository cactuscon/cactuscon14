"""Battle rules engine - Central orchestrator for ALL battle logic."""

import urandom
from micropython import const


from cactuscon.game.engine.moves import (
    get_move, Move,
    MOVE_TYPE_PHYSICAL,
)
from cactuscon.game.engine.characters import (
    get_character,
    get_care_catalog,
    CharacterStats,
)
from cactuscon.game.engine.achievements import get_achievement_powers
from cactuscon.game.engine.status_effects import (
    StatusEffect, StatusEffectType,
    create_burn_effect, create_poison_effect, create_paralyze_effect,
    create_sleep_effect, create_confuse_effect,
)


# Battle result constants
BATTLE_CONTINUES = const(0)
PLAYER_WINS = const(1)
OPPONENT_WINS = const(2)
BATTLE_DRAW = const(3)


class BattleContext:
    """
    Pure data container holding battle state for both combatants.
    
    Tracks HP, stats, status effects, and move usage for a battle.
    Used by BattleManager to maintain state across turns.
    
    Attributes:
        player_char (Character): Player's character.
        opponent_char (Character): Opponent's character.
        player_stats (CharacterStats): Player's battle stats (modified during battle).
        opponent_stats (CharacterStats): Opponent's battle stats.
        player_moves (list): Move IDs available to player.
        opponent_moves (list): Move IDs available to opponent.
        turn_number (int): Current turn count.
        battle_log (list): Log of battle events.
    """
    
    __slots__ = ('player_char', 'player_stats', 'player_moves',
                 'opponent_char', 'opponent_stats', 'opponent_moves',
                 'turn_number', 'battle_log')
    
    def __init__(self, player_char=None, opponent_char=None):
        """
        Initialize battle context.
        
        Args:
            player_char (Character): Player's character.
            opponent_char (Character): Opponent's character.
        """
        self.player_char = player_char
        self.opponent_char = opponent_char
        
        if player_char:
            self.player_stats = player_char.get_battle_stats()
            self.player_moves = list(player_char.moves)
        else:
            self.player_stats = CharacterStats()
            self.player_moves = [0, 1, 2, 3]
        
        if opponent_char:
            self.opponent_stats = opponent_char.get_battle_stats()
            self.opponent_moves = list(opponent_char.moves)
        else:
            self.opponent_stats = CharacterStats()
            self.opponent_moves = [0, 1, 2, 3]
        
        self.turn_number = 0
        self.battle_log = []
    
    def log(self, message):
        """Add message to battle log."""
        self.battle_log.append((self.turn_number, message))
    
    def advance_turn(self):
        """Increment turn counter."""
        self.turn_number += 1
    
    def get_player_stats_dict(self):
        """Get player stats as dict for protocol."""
        return self.player_stats.to_dict()
    
    def get_opponent_stats_dict(self):
        """Get opponent stats as dict for protocol."""
        return self.opponent_stats.to_dict()
    
    def is_battle_over(self):
        """Check if either combatant is KO'd."""
        return self.player_stats.hp <= 0 or self.opponent_stats.hp <= 0


class BattleRules:
    """
    Central orchestrator for ALL battle logic in CactusCon badge game.
    
    This is THE single source of truth for all battle mechanics.
    ALL action resolution, turn flow, and state transitions pass through
    this class. Other classes are pure data containers or protocol bridges.
    
    Role Separation:
        - Move, Character, Station: Pure data (attributes only, no logic)
        - BattleManager: Protocol bridge (BT comms <-> UI), delegates ALL logic here
        - BattleRules: ALL game evaluation and state management
        - ConsensusTracker: Verifies both devices agree on outcomes
    
    CONSENSUS SUPPORT:
        For networked battles, set_rng() with a DeterministicRNG seeded from
        turn data. All random operations use this RNG to ensure both devices
        produce identical results. Call clear_rng() after turn resolution.
    
    Key Entry Points:
        execute_action()        - THE main entry point for all actions
        calculate_turn_order()  - Determine who moves first
        check_victory_condition() - Check battle end state
    
    Full API:
        ACTIONS:
            execute_action(move, attacker, defender) -> (value, result_dict)
            
        DAMAGE:
            calculate_damage(move, attacker, defender) -> (damage, is_crit)
            
        HEALING:
            calculate_healing(move, user) -> heal_amount
            
        STATUS:
            apply_status_effect(effect, target) -> result_dict
            update_status_effects(stats) -> list[messages]
            check_action_prevented(stats) -> (prevented, message)
            
        TURNS:
            calculate_turn_order(p_move, p_stats, o_move, o_stats) -> bool
            on_turn_start(player_stats, opponent_stats) -> messages
            on_turn_end(player_stats, opponent_stats) -> messages
            
        VICTORY:
            check_victory_condition(player, opponent) -> BATTLE_* constant
            
        VALIDATION:
            validate_action(move, attacker_stats, character=None) -> (valid, error)
            get_available_moves(character, stats) -> list[Move]
            
        STATE:
            get_initial_stats(character=None) -> dict
            is_battle_over(player_stats, opponent_stats) -> bool
            
        LIFECYCLE:
            on_battle_start(player_stats, opponent_stats) -> None
            on_battle_end(winner, player_stats, opponent_stats) -> result_dict
            
        CONSENSUS (for networked battles):
            set_rng(rng) - Set deterministic RNG for current turn
            clear_rng() - Clear RNG after turn (fallback to urandom)
            get_random() - Get random float 0-1 (uses RNG if set)
    
    Subclasses:
        Override specific methods to customize behavior:
        - calculate_damage() for different damage formulas
        - get_type_effectiveness() for elemental types
        - on_battle_end() for custom rewards
    
    Example:
        rules = BattleRules()
        
        player = get_character('hacktarmon')
        opponent = get_character('deeno')
        
        player_stats = player.get_battle_stats()
        opponent_stats = opponent.get_battle_stats()
        
        rules.on_battle_start(player_stats.to_dict(), opponent_stats.to_dict())
        
        # For consensus: set RNG before executing
        rng = DeterministicRNG(turn_seed)
        rules.set_rng(rng)
        
        move = get_move(1)  # Byte Strike
        valid, error = rules.validate_action(move, player_stats, player)
        if valid:
            damage, result = rules.execute_action(move, player_stats, opponent_stats)
            winner = rules.check_victory_condition(player_stats, opponent_stats)
        
        rules.clear_rng()  # After turn complete
    """
    
    # ==================== Configuration (override in subclasses) ====================
    
    # Damage formula constants
    BASE_DAMAGE_MULTIPLIER = 2.15  # Scales base damage
    CRIT_MULTIPLIER = 1.850         # Critical hit bonus
    CRIT_CHANCE = 0.0750            # 1/16 chance (6.25%)
    MIN_DAMAGE = 5                  # Minimum damage for any hit
    
    # Random variation range (damage varies between MIN and MAX percent)
    DAMAGE_VARIATION_MIN = 0.75
    DAMAGE_VARIATION_MAX = 1

    # Global tunables
    EVASION_EFFECT_MULT = 2.5     # Scales evasion accuracy reduction
    DEFENSE_EFFICIENCY_MULT = 0.9 # Scales defense effectiveness in damage calc
    
    def __init__(self):
        """Initialize battle rules."""
        self._rng = None  # Deterministic RNG for consensus (None = use urandom)

    # ==================== Care Modifiers ====================

    def _get_care_effect(self, category, effect_id):
        catalog = get_care_catalog() or {}
        for effect in catalog.get(category, []):
            if effect.get("id") == effect_id:
                return effect
        return None

    def _get_power_effect(self, power_id):
        return get_achievement_powers().get(power_id)

    def normalize_care_effects(self, care_effects):
        """
        Normalize care effect IDs to known catalog entries.

        Args:
            care_effects (dict): {'activity': id, 'food': id}

        Returns:
            dict: Normalized effect IDs with unknown entries cleared.
        """
        normalized = {"activity": None, "food": None}
        if not care_effects:
            return normalized
        for category in ("activity", "food"):
            effect_id = care_effects.get(category)
            if effect_id and self._get_care_effect(category, effect_id):
                normalized[category] = effect_id
        return normalized

    def apply_care_modifiers(self, stats, care_effects):
        """
        Apply care-based stat modifiers (attack/defense) to stats.

        Returns:
            dict: Aggregate modifiers applied (atk_delta, def_delta, xp_boost_pct).
        """
        normalized = self.normalize_care_effects(care_effects)
        atk_delta = 0
        def_delta = 0
        xp_boost_pct = 0

        for category in ("activity", "food"):
            effect_id = normalized.get(category)
            effect = self._get_care_effect(category, effect_id) if effect_id else None
            if not effect:
                continue
            atk_delta += effect.get("atk_delta", 0)
            def_delta += effect.get("def_delta", 0)
            xp_boost_pct += effect.get("xp_boost_pct", 0)

        if atk_delta or def_delta:
            if isinstance(stats, CharacterStats):
                stats.attack = max(1, stats.attack + atk_delta)
                stats.defense = max(1, stats.defense + def_delta)
            else:
                stats["attack"] = max(1, stats.get("attack", 1) + atk_delta)
                stats["defense"] = max(1, stats.get("defense", 1) + def_delta)

        return {
            "atk_delta": atk_delta,
            "def_delta": def_delta,
            "xp_boost_pct": xp_boost_pct,
        }

    # ==================== Achievement Power Modifiers ====================

    def normalize_power_effects(self, power_ids):
        """Return list of valid achievement power IDs."""
        if not power_ids:
            return []
        power_catalog = get_achievement_powers()
        if isinstance(power_ids, dict):
            source_ids = power_ids.values()
        elif isinstance(power_ids, (list, tuple, set)):
            source_ids = power_ids
        else:
            # Accept single IDs or unexpected scalar input without raising.
            source_ids = (power_ids,)
        normalized = []
        for pid in source_ids:
            if not pid:
                continue
            if isinstance(pid, bytes):
                try:
                    pid = pid.decode("utf-8")
                except Exception:
                    continue
            if pid and pid in power_catalog:
                normalized.append(pid)
        # de-dup
        return list(dict.fromkeys(normalized))

    def apply_power_modifiers(self, stats, power_ids):
        """
        Apply achievement power stat modifiers to stats object/dict.

        Returns:
            dict: Aggregate modifiers applied.
        """
        normalized = self.normalize_power_effects(power_ids)
        atk_delta = 0
        def_delta = 0
        speed_delta = 0
        xp_boost_pct = 0

        for pid in normalized:
            effect = self._get_power_effect(pid)
            if not effect:
                continue
            atk_delta += effect.get("atk_delta", 0)
            def_delta += effect.get("def_delta", 0)
            # Convert evasion bonus into speed to avoid stacking with evasion moves
            evasion_bonus = effect.get("evasion_delta", 0)
            if evasion_bonus:
                speed_delta += evasion_bonus * 3  # ratio 3:1 ~ +5 evasion => +15 speed
            xp_boost_pct += effect.get("xp_boost_pct", 0)

        if atk_delta:
            if isinstance(stats, CharacterStats):
                stats.attack = max(1, stats.attack + atk_delta)
            else:
                stats["attack"] = max(1, stats.get("attack", 1) + atk_delta)
        if def_delta:
            if isinstance(stats, CharacterStats):
                stats.defense = max(1, stats.defense + def_delta)
            else:
                stats["defense"] = max(1, stats.get("defense", 1) + def_delta)
        if speed_delta:
            if isinstance(stats, CharacterStats):
                stats.speed = max(1, stats.speed + speed_delta)
            else:
                stats["speed"] = max(1, stats.get("speed", 1) + speed_delta)

        return {
            "atk_delta": atk_delta,
            "def_delta": def_delta,
            "speed_delta": speed_delta,
            "xp_boost_pct": xp_boost_pct,
        }
    
    # ==================== RNG Management (for consensus) ====================
    
    def set_rng(self, rng):
        """
        Set deterministic RNG for consensus-based battles.
        
        Call this at the start of each turn with an RNG seeded from
        the shared turn data. Both devices must use the same seed.
        
        Args:
            rng (DeterministicRNG): Seeded RNG for this turn.
        """
        self._rng = rng
    
    def clear_rng(self):
        """Clear deterministic RNG after turn resolution."""
        self._rng = None
    
    def get_random(self):
        """
        Get random float in [0, 1).
        
        Uses deterministic RNG if set (for consensus), otherwise urandom.
        
        Returns:
            float: Random value.
        """
        if self._rng is not None:
            val = self._rng.random()
            #print(f"[RNG] get_random() = {val:.6f}")
            return val
        return urandom.random()
    
    def get_random_uniform(self, low, high):
        """
        Get random float in [low, high).
        
        Args:
            low (float): Lower bound.
            high (float): Upper bound.
            
        Returns:
            float: Random value in range.
        """
        if self._rng is not None:
            val = self._rng.uniform(low, high)
            #print(f"[RNG] get_random_uniform({low}, {high}) = {val:.6f}")
            return val
        return low + urandom.random() * (high - low)
    
    # ==================== ACTIONS: Main Entry Point ====================
    
    def execute_action(self, move, attacker_stats, defender_stats):
        """
        Execute an action and apply all effects.
        
        THIS IS THE MAIN ENTRY POINT FOR ALL BATTLE ACTIONS.
        Routes to appropriate handler based on move type.
        
        Args:
            move (Move or int): Move instance or move_id.
            attacker_stats (CharacterStats or dict): Attacker's stats.
            defender_stats (CharacterStats or dict): Defender's stats (modified).
            
        Returns:
            tuple: (damage_or_heal (int), result_dict)
                result_dict contains: hit, critical, effect_applied, messages
        """
        # Normalize move to Move instance
        if isinstance(move, int):
            move = get_move(move)
        if not move:
            return (0, {'hit': False, 'messages': ['Unknown move!']})
        
        # Normalize stats to dict if CharacterStats
        atk_dict = attacker_stats.to_dict() if isinstance(attacker_stats, CharacterStats) else attacker_stats
        def_dict = defender_stats.to_dict() if isinstance(defender_stats, CharacterStats) else defender_stats
        
        result = {
            'move_id': move.id,
            'move_name': move.name,
            'hit': True,
            'damage': 0,
            'healed': 0,
            'critical': False,
            'effect_applied': None,
            'messages': [],
        }
        
        # Route to appropriate handler based on move type
        if move.is_damaging():
            damage, hit, crit = self._execute_damage_move(move, atk_dict, def_dict, defender_stats)
            result['damage'] = damage
            result['hit'] = hit
            result['critical'] = crit
            
            if not hit:
                result['messages'].append(f"{move.name} missed!")
            elif crit:
                result['messages'].append(f"Critical hit! {move.name} dealt {damage} damage!")
            else:
                result['messages'].append(f"{move.name} dealt {damage} damage!")
            
            # Apply damage to defender
            if hit and damage > 0:
                self._apply_damage(def_dict, damage, defender_stats)
        
        elif move.is_healing():
            healed = self._execute_heal_move(move, atk_dict)
            result['healed'] = healed
            result['messages'].append(f"Restored {healed} HP!")
            
            # Apply heal to attacker
            self._apply_heal(atk_dict, healed, attacker_stats)
        
        elif move.is_status():
            effect_result = self._execute_status_move(
                move, atk_dict, def_dict, defender_stats, attacker_stats
            )
            result['effect_applied'] = effect_result
            if effect_result.get('success'):
                result['messages'].append(f"Applied {move.effect}!")
            else:
                result['messages'].append(f"{move.effect} failed!")
        
        return (result['damage'] or result['healed'], result)
    
    def _apply_damage(self, stats_dict, damage, stats_obj=None):
        """Apply damage to stats dict and optionally sync to CharacterStats."""
        stats_dict['hp'] = max(0, stats_dict.get('hp', 100) - damage)
        if isinstance(stats_obj, CharacterStats):
            stats_obj.hp = stats_dict['hp']
    
    def _apply_heal(self, stats_dict, heal_amount, stats_obj=None):
        """Apply healing to stats dict and optionally sync to CharacterStats."""
        max_hp = stats_dict.get('max_hp', 100)
        stats_dict['hp'] = min(max_hp, stats_dict.get('hp', 0) + heal_amount)
        if isinstance(stats_obj, CharacterStats):
            stats_obj.hp = stats_dict['hp']
    
    # ==================== Damage Calculation ====================
    
    def _execute_damage_move(self, move, attacker_stats, defender_stats, defender_obj=None):
        """
        Execute a damage-dealing move.
        
        Returns:
            tuple: (damage, hit, critical)
        """
        #print(f"[RULES] _execute_damage_move: {move.name} (id={move.id})")
        
        # Accuracy check
        if not self._check_accuracy(move, attacker_stats, defender_stats):
            self._consume_defense_evasion(defender_stats, defender_obj, move)
            return (0, False, False)
        
        # Calculate damage
        damage, critical = self.calculate_damage(move, attacker_stats, defender_stats)
        self._consume_defense_evasion(defender_stats, defender_obj, move)
        
        return (damage, True, critical)

    def _get_move_element(self, move):
        if not move:
            return None
        try:
            return move.extra.get('element')
        except Exception:
            return None
    
    def calculate_damage(self, move, attacker_stats, defender_stats):
        """
        Calculate damage from an attack move.
        
        Uses deterministic RNG if set (for consensus), otherwise urandom.
        Override this method to implement different damage formulas.
        
        Args:
            move (Move): Move being used.
            attacker_stats (dict): Attacker's stats.
            defender_stats (dict): Defender's stats.
            
        Returns:
            tuple: (damage (int), was_critical (bool))
        """
        # Get relevant attack/defense stats based on move type
        if move.move_type == MOVE_TYPE_PHYSICAL:
            attack = attacker_stats.get('attack', 10)
            defense = defender_stats.get('defense', 10)
            if defender_stats.get('defense_turns', 0) > 0:
                defense = int(defense * defender_stats.get('defense_mult', 1.0))
        else:  # MOVE_TYPE_SPECIAL
            attack = attacker_stats.get('sp_attack', attacker_stats.get('attack', 10))
            defense = defender_stats.get('sp_defense', defender_stats.get('defense', 10))
            if defender_stats.get('sp_defense_turns', 0) > 0:
                defense = int(defense * defender_stats.get('sp_defense_mult', 1.0))

        defense = int(defense * self.DEFENSE_EFFICIENCY_MULT)
        
        # Base damage calculation
        # Formula: (Power + Attack - Defense) * multiplier
        base_damage = (move.power + attack) - max(defense, 1)
        base_damage *= self.BASE_DAMAGE_MULTIPLIER

        # For applying level-based modifiers
        attacker_level = attacker_stats.get('level', 1)
        base_damage *= 1 + (attacker_level * 0.025)
        
        # Type effectiveness (override get_type_effectiveness for elemental systems)
        effectiveness = self.get_type_effectiveness(move, attacker_stats, defender_stats)
        base_damage *= effectiveness

        # Element-matched defense move halves damage for 2 incoming attacks
        move_elem = self._get_move_element(move)
        if move_elem:
            if move.move_type == MOVE_TYPE_PHYSICAL:
                if defender_stats.get('defense_turns', 0) > 0 and defender_stats.get('defense_elem') == move_elem:
                    base_damage *= 0.5
            else:
                if defender_stats.get('sp_defense_turns', 0) > 0 and defender_stats.get('sp_defense_elem') == move_elem:
                    base_damage *= 0.5
        
        # Random variation (uses deterministic RNG for consensus)
        variation = self.get_random_uniform(self.DAMAGE_VARIATION_MIN, self.DAMAGE_VARIATION_MAX)
        damage = base_damage * variation
        
        # Critical hit check (uses deterministic RNG for consensus)
        critical = self.get_random() < self.CRIT_CHANCE
        if defender_stats.get('evasion_turns', 0) > 0:
            critical = False
        if critical:
            damage *= self.CRIT_MULTIPLIER

        # Ensure minimum damage
        final_damage = max(self.MIN_DAMAGE, int(damage))
        #print(f"[RULES] calculate_damage: move={move.name}, power={move.power}, attack={attack}, defense={defense}, base_damage={base_damage}, variation={variation:.2f}, final_damage={final_damage}")
        
        return (final_damage, critical)
    
    def get_type_effectiveness(self, move, attacker_stats, defender_stats):
        """
        Get type effectiveness multiplier.
        
        Override this for elemental type systems (fire > grass > water > fire).
        Default implementation returns 1.0 (neutral).
        
        Args:
            move (Move): Move being used.
            attacker_stats (dict): Attacker's stats.
            defender_stats (dict): Defender's stats.
            
        Returns:
            float: Multiplier (0.5 = not effective, 1.0 = neutral, 2.0 = super effective)
        """
        return 1.0
    
    def _check_accuracy(self, move, attacker_stats, defender_stats):
        """
        Check if move hits based on accuracy.
        
        Uses deterministic RNG if set (for consensus).
        
        Args:
            move (Move): Move being used.
            attacker_stats (dict): Attacker's stats.
            defender_stats (dict): Defender's stats.
            
        Returns:
            bool: True if move hits.
        """
        # Roll for accuracy (uses deterministic RNG for consensus)
        # Notes:
        # - base_miss increases as attacker speed drops (floor 2%).
        # - speed_penalty applies only if defender is faster.
        # - evasion applies only while active (evasion_turns > 0).
        #
        # Example 1:
        #   attacker_speed=20 -> base_miss=max(2, 10 - 4)=6
        #   defender_speed=10 -> speed_penalty=0
        #   evasion=0
        #   effective_accuracy = move.accuracy - 6
        #
        # Example 2 (fast defender + evasion):
        #   attacker_speed=10 -> base_miss=max(2, 10 - 2)=8
        #   defender_speed=20 -> speed_penalty=(20-10)*0.5=5
        #   evasion=15
        #   effective_accuracy = move.accuracy - 8 - 5 - 15
        attacker_speed = attacker_stats.get('speed', 10)
        defender_speed = defender_stats.get('speed', 10)
        base_miss = max(2.0, 10.0 - ((attacker_speed * self.EVASION_EFFECT_MULT) * 0.2))
        speed_penalty = max(0.0, (defender_speed - attacker_speed) * 0.5)
        evasion = defender_stats.get('evasion', 0) if defender_stats.get('evasion_turns', 0) > 0 else 0
        evasion *= self.EVASION_EFFECT_MULT
        effective_accuracy = move.accuracy - base_miss - speed_penalty - evasion
        effective_accuracy = max(5.0, min(100.0, effective_accuracy))
        roll = self.get_random() * 100
        return roll < effective_accuracy
    
    # ==================== Healing ====================
    
    def _execute_heal_move(self, move, user_stats):
        """
        Execute a healing move.
        
        Args:
            move (Move): Healing move.
            user_stats (dict): User's stats.
            
        Returns:
            int: Amount healed.
        """
        max_hp = user_stats.get('max_hp', 100)
        heal_percent = move.heal_percent if move.heal_percent else 25
        return int(max_hp * heal_percent / 100)
    
    # ==================== Status Effects ====================
    
    def _execute_status_move(self, move, user_stats, target_stats, target_obj=None, user_obj=None):
        """
        Execute a status effect move.
        
        Args:
            move (Move): Status move.
            user_stats (dict): User's stats.
            target_stats (dict): Target's stats dict.
            target_obj: Target CharacterStats (optional).
            
        Returns:
            dict: Result with success, effect name.
        """
        if not move.effect:
            return {'success': False, 'reason': 'no_effect'}
        
        effect_name = move.effect.lower()
        
        # Handle stat boosts (apply to user, not target)
        if effect_name in ('defense_up', 'speed_up', 'attack_up', 'sp_defense_up', 'evasion_up'):
            if effect_name == 'evasion_up':
                return self._apply_evasion_boost(user_stats, user_obj)
            return self._apply_stat_boost(
                effect_name,
                user_stats,
                user_obj,
                source_element=self._get_move_element(move),
            )
        
        # Handle debilitating effects (apply to target)
        return self.apply_status_effect(effect_name, target_stats, target_obj)
    
    def apply_status_effect(self, effect_name, target_stats, target_obj=None):
        """
        Apply a status effect to target.
        
        Override to customize status effect behavior.
        
        Args:
            effect_name (str): Effect name (poison, burn, etc.)
            target_stats (dict): Target's stats dict.
            target_obj: Target CharacterStats (optional).
            
        Returns:
            dict: Result with success flag.
        """
        effect_map = {
            'poison': (StatusEffectType.POISON, create_poison_effect),
            'burn': (StatusEffectType.BURN, create_burn_effect),
            'paralyze': (StatusEffectType.PARALYZE, create_paralyze_effect),
            'sleep': (StatusEffectType.SLEEP, lambda: create_sleep_effect(3)),
            'confuse': (StatusEffectType.CONFUSE, lambda: create_confuse_effect(3)),
        }
        
        if effect_name not in effect_map:
            return {'success': False, 'reason': 'unknown_effect'}
        
        effect_type, creator = effect_map[effect_name]
        
        # Check if already has this effect
        status_effects = target_stats.get('status_effects', [])
        for existing in status_effects:
            if isinstance(existing, StatusEffect) and existing.effect_type == effect_type:
                return {'success': False, 'reason': 'already_affected'}
        
        # Create and apply effect
        effect = creator()
        status_effects.append(effect)
        target_stats['status_effects'] = status_effects
        
        # Apply immediate stat modifiers
        effect.apply_to_stats(target_stats)
        
        # Sync to CharacterStats if provided
        if isinstance(target_obj, CharacterStats):
            target_obj.status_effects = status_effects
        
        return {'success': True, 'effect': effect.get_name()}
    
    def _apply_stat_boost(self, boost_type, stats, stats_obj=None, source_element=None):
        """Apply a stat boost effect to user."""
        if boost_type in ('defense_up', 'sp_defense_up'):
            mult_key = 'defense_mult' if boost_type == 'defense_up' else 'sp_defense_mult'
            turns_key = 'defense_turns' if boost_type == 'defense_up' else 'sp_defense_turns'
            elem_key = 'defense_elem' if boost_type == 'defense_up' else 'sp_defense_elem'
            user_level = stats_obj.level if isinstance(stats_obj, CharacterStats) else stats.get('level', 1)
            stats[mult_key] = 1.5 + (user_level * 0.025)
            stats[turns_key] = 2
            stats[elem_key] = source_element
            if isinstance(stats_obj, CharacterStats):
                setattr(stats_obj, mult_key, stats[mult_key])
                setattr(stats_obj, turns_key, stats[turns_key])
                setattr(stats_obj, elem_key, stats[elem_key])
            return {'success': True, 'stat': mult_key, 'new_value': stats[mult_key]}

        boost_map = {
            'speed_up': ('speed', 1.5),
            'attack_up': ('attack', 1.5),
        }
        
        if boost_type not in boost_map:
            return {'success': False}
        
        stat_name, multiplier = boost_map[boost_type]
        current = stats.get(stat_name, 10)
        stats[stat_name] = int(current * multiplier)
        if isinstance(stats_obj, CharacterStats):
            setattr(stats_obj, stat_name, stats[stat_name])
        
        return {'success': True, 'stat': stat_name, 'new_value': stats[stat_name]}

    def _apply_evasion_boost(self, stats, stats_obj=None):
        """Apply a flat evasion boost for 2 incoming attacks."""
        current = stats.get('evasion', 0)
        stats['evasion'] = min(60, current + 15)
        stats['evasion_turns'] = 2
        if isinstance(stats_obj, CharacterStats):
            stats_obj.evasion = stats['evasion']
            stats_obj.evasion_turns = stats['evasion_turns']
        return {'success': True, 'stat': 'evasion', 'new_value': stats['evasion']}

    def _consume_defense_evasion(self, defender_stats, defender_obj, move):
        """Consume temporary defense/evasion per incoming damaging move."""
        if not move.is_damaging():
            return

        if defender_stats.get('defense_turns', 0) > 0:
            defender_stats['defense_turns'] -= 1
            if defender_stats['defense_turns'] <= 0:
                defender_stats['defense_turns'] = 0
                defender_stats['defense_mult'] = 1.0
                defender_stats['defense_elem'] = None

        if defender_stats.get('sp_defense_turns', 0) > 0:
            defender_stats['sp_defense_turns'] -= 1
            if defender_stats['sp_defense_turns'] <= 0:
                defender_stats['sp_defense_turns'] = 0
                defender_stats['sp_defense_mult'] = 1.0
                defender_stats['sp_defense_elem'] = None

        if defender_stats.get('evasion_turns', 0) > 0:
            defender_stats['evasion_turns'] -= 1
            if defender_stats['evasion_turns'] <= 0:
                defender_stats['evasion_turns'] = 0
                defender_stats['evasion'] = 0

        if isinstance(defender_obj, CharacterStats):
            defender_obj.defense_turns = defender_stats.get('defense_turns', 0)
            defender_obj.defense_mult = defender_stats.get('defense_mult', 1.0)
            defender_obj.defense_elem = defender_stats.get('defense_elem', None)
            defender_obj.sp_defense_turns = defender_stats.get('sp_defense_turns', 0)
            defender_obj.sp_defense_mult = defender_stats.get('sp_defense_mult', 1.0)
            defender_obj.sp_defense_elem = defender_stats.get('sp_defense_elem', None)
            defender_obj.evasion_turns = defender_stats.get('evasion_turns', 0)
            defender_obj.evasion = defender_stats.get('evasion', 0)
    
    def update_status_effects(self, stats):
        """
        Process status effects at end of turn.
        
        Applies damage-over-time effects and decrements durations.
        
        Args:
            stats (dict or CharacterStats): Entity stats.
            
        Returns:
            list: Messages from effect processing.
        """
        stats_dict = stats.to_dict() if isinstance(stats, CharacterStats) else stats
        messages = []
        status_effects = stats_dict.get('status_effects', [])
        remaining_effects = []
        
        for effect in status_effects:
            if not isinstance(effect, StatusEffect):
                continue
            
            damage, message, expired = effect.tick(stats_dict)
            
            if message:
                messages.append(message)
            
            if not expired:
                remaining_effects.append(effect)
            else:
                messages.append(f"{effect.get_name()} wore off!")
        
        stats_dict['status_effects'] = remaining_effects
        
        # Sync back to CharacterStats if provided
        if isinstance(stats, CharacterStats):
            stats.hp = stats_dict['hp']
            stats.status_effects = remaining_effects
        
        return messages
    
    def check_action_prevented(self, stats):
        """
        Check if status effects prevent action this turn.
        
        Uses deterministic RNG if set (for consensus).
        
        Args:
            stats (dict or CharacterStats): Entity stats.
            
        Returns:
            tuple: (prevented (bool), message (str or None)).
        """
        stats_dict = stats.to_dict() if isinstance(stats, CharacterStats) else stats
        status_effects = stats_dict.get('status_effects', [])
        
        for effect in status_effects:
            if isinstance(effect, StatusEffect):
                # Pass RNG for deterministic status checks
                prevented, message = effect.prevents_action(rng=self._rng)
                if prevented:
                    return (True, message)
        
        return (False, None)
    
    # ==================== Turn Order ====================
    
    def get_move_priority(self, move):
        """
        Get move's priority value.
        
        Args:
            move (Move or int): Move or move_id.
            
        Returns:
            int: Priority value (higher goes first).
        """
        if isinstance(move, int):
            move = get_move(move)
        return move.priority if move else 0
    
    def calculate_turn_order(self, player_move, player_stats, opponent_move, opponent_stats, is_challenger=True):
        """
        Determine who moves first based on priority and speed.
        
        Uses challenger-wins tiebreaker for speed ties (deterministic for consensus).
        
        Turn order rules:
        1. Higher priority move goes first
        2. If same priority, higher speed goes first
        3. If same speed, challenger goes first (deterministic tiebreaker)
        
        Args:
            player_move: Move or (move_id, move_data) tuple.
            player_stats (dict or CharacterStats): Player's stats.
            opponent_move: Move or (move_id, move_data) tuple.
            opponent_stats (dict or CharacterStats): Opponent's stats.
            is_challenger: True if player is the challenger (for tiebreaker).
            
        Returns:
            bool: True if player goes first.
        """
        # Extract move_id from tuple if needed
        player_move_id = player_move[0] if isinstance(player_move, tuple) else (player_move.id if isinstance(player_move, Move) else player_move)
        opponent_move_id = opponent_move[0] if isinstance(opponent_move, tuple) else (opponent_move.id if isinstance(opponent_move, Move) else opponent_move)
        
        player_priority = self.get_move_priority(player_move_id)
        opponent_priority = self.get_move_priority(opponent_move_id)
        
        # Priority check
        if player_priority > opponent_priority:
            return True
        elif opponent_priority > player_priority:
            return False
        
        # Speed check
        p_stats = player_stats.to_dict() if isinstance(player_stats, CharacterStats) else player_stats
        o_stats = opponent_stats.to_dict() if isinstance(opponent_stats, CharacterStats) else opponent_stats
        
        player_speed = p_stats.get('speed', 10)
        opponent_speed = o_stats.get('speed', 10)
        
        if player_speed > opponent_speed:
            return True
        elif opponent_speed > player_speed:
            return False
        
        # Speed tie - challenger goes first (deterministic tiebreaker for consensus)
        # If we're the challenger, we go first; if not, opponent (the challenger) goes first
        return is_challenger
    
    # ==================== Victory Conditions ====================
    
    def check_victory_condition(self, player_stats, opponent_stats):
        """
        Check if battle has ended and determine winner.
        
        Args:
            player_stats (dict or CharacterStats): Player's stats.
            opponent_stats (dict or CharacterStats): Opponent's stats.
            
        Returns:
            int: BATTLE_CONTINUES (0), PLAYER_WINS (1), OPPONENT_WINS (2), BATTLE_DRAW (3)
        """
        p_stats = player_stats.to_dict() if isinstance(player_stats, CharacterStats) else player_stats
        o_stats = opponent_stats.to_dict() if isinstance(opponent_stats, CharacterStats) else opponent_stats
        
        player_hp = p_stats.get('hp', 0)
        opponent_hp = o_stats.get('hp', 0)
        
        if player_hp <= 0 and opponent_hp <= 0:
            return BATTLE_DRAW
        elif opponent_hp <= 0:
            return PLAYER_WINS
        elif player_hp <= 0:
            return OPPONENT_WINS
        
        return BATTLE_CONTINUES
    
    # ==================== Move Validation ====================
    
    def validate_move(self, move, attacker_stats, character=None):
        """
        Validate if a move can be used.
        
        Checks:
        - Move exists
        - Character knows the move (if character provided)
        - No status prevents using moves
        
        Args:
            move (Move or int): Move to validate.
            attacker_stats (dict or CharacterStats): Attacker's stats.
            character (Character, optional): Character using the move.
            
        Returns:
            tuple: (is_valid (bool), error_message (str or None))
        """
        # Normalize move
        if isinstance(move, int):
            move = get_move(move)
        if not move:
            return (False, "Unknown move")
        
        # Check character knows the move
        if character and not character.can_use_move(move.id):
            return (False, f"{character.name} doesn't know {move.name}!")
        
        # Check status effects that prevent action
        prevented, message = self.check_action_prevented(attacker_stats)
        if prevented:
            return (False, message)
        
        return (True, None)
    
    # ==================== Battle Lifecycle ====================
    
    def get_initial_stats(self, character=None):
        """
        Get initial battle stats.
        
        Args:
            character (Character or str, optional): Character to get stats for.
            
        Returns:
            dict: Initial stats for battle.
        """
        if character:
            if isinstance(character, str):
                character = get_character(character)
            if character:
                return character.get_battle_stats_dict()
        
        # Default stats if no character
        return {
            'hp': 100,
            'max_hp': 100,
            'attack': 15,
            'defense': 12,
            'sp_attack': 15,
            'sp_defense': 12,
            'speed': 12,
            'status': 0,
            'status_effects': [],
            'evasion': 0,
            'evasion_turns': 0,
            'defense_turns': 0,
            'defense_mult': 1.0,
            'defense_elem': None,
            'sp_defense_turns': 0,
            'sp_defense_mult': 1.0,
            'sp_defense_elem': None,
        }
    
    def on_battle_start(self, player_stats, opponent_stats):
        """
        Called when battle starts (setup phase).
        
        Override for custom battle start behavior.
        
        Args:
            player_stats (dict): Player's stats (can be modified).
            opponent_stats (dict): Opponent's stats (can be modified).
        """
        # Clear any existing status effects
        player_stats['status_effects'] = []
        opponent_stats['status_effects'] = []
        player_stats['status'] = 0
        opponent_stats['status'] = 0
        player_stats['evasion'] = 0
        opponent_stats['evasion'] = 0
        player_stats['evasion_turns'] = 0
        opponent_stats['evasion_turns'] = 0
        player_stats['defense_turns'] = 0
        opponent_stats['defense_turns'] = 0
        player_stats['defense_mult'] = 1.0
        opponent_stats['defense_mult'] = 1.0
        player_stats['defense_elem'] = None
        opponent_stats['defense_elem'] = None
        player_stats['sp_defense_turns'] = 0
        opponent_stats['sp_defense_turns'] = 0
        player_stats['sp_defense_mult'] = 1.0
        opponent_stats['sp_defense_mult'] = 1.0
        player_stats['sp_defense_elem'] = None
        opponent_stats['sp_defense_elem'] = None
    
    def on_battle_end(
        self,
        winner,
        player_stats,
        opponent_stats,
        turn_count=None,
        battle_log=None,
        player_care_effects=None,
        player_power_effects=None,
    ):
        """
        Called when battle ends (cleanup/rewards phase).
        
        Args:
            winner (int): PLAYER_WINS, OPPONENT_WINS, or BATTLE_DRAW.
            player_stats (dict): Final player stats.
            opponent_stats (dict): Final opponent stats.
            turn_count (int, optional): Number of turns the battle lasted.
            battle_log (list, optional): Battle event log.
            player_care_effects (dict, optional): Active care effects for XP boosts.
            
        Returns:
            dict: Battle results (xp_gained, rewards, turns, battle_log).
        """
        result = {
            'winner': winner,
            'xp_gained': 0,
            'xp_gained_base': 0,
            'xp_boost_pct': 0,
            'rewards': [],
            'turns': turn_count or 0,
            'battle_log': battle_log or [],
        }
        
        # New XP formula: both sides earn XP (no draw), based on average HP and damage taken
        # xp = max(0, avg_hp - (local_max_hp - local_end_hp))
        player_max = player_stats.get('max_hp', 100)
        opp_max = opponent_stats.get('max_hp', 100)
        player_end = max(0, player_stats.get('hp', 0))
        avg_hp = (player_max + opp_max) // 2
        xp_local = max(50, avg_hp - (player_max - player_end))

        if winner == PLAYER_WINS:
            result['xp_gained'] = xp_local
            result['rewards'].append('victory')
        elif winner == OPPONENT_WINS:
            # If we lost, award half of what winner would get on their side
            result['xp_gained'] = xp_local // 2
            result['rewards'].append('defeat')
        else:  # Draw
            result['xp_gained'] = 0
            result['rewards'].append('draw')

        xp_boost_pct = 0
        if player_care_effects:
            normalized = self.normalize_care_effects(player_care_effects)
            for category in ("activity", "food"):
                effect_id = normalized.get(category)
                effect = self._get_care_effect(category, effect_id) if effect_id else None
                if effect:
                    xp_boost_pct += effect.get("xp_boost_pct", 0)
        if player_power_effects:
            normalized_p = self.normalize_power_effects(player_power_effects)
            for pid in normalized_p:
                effect = self._get_power_effect(pid)
                if effect:
                    xp_boost_pct += effect.get("xp_boost_pct", 0)

        result['xp_gained_base'] = result['xp_gained']
        result['xp_boost_pct'] = xp_boost_pct
        if xp_boost_pct:
            result['xp_gained'] = int(
                (result['xp_gained'] * (100 + xp_boost_pct)) / 100
            )

        return result
    
    # ==================== TURN LIFECYCLE ====================
    
    def on_turn_start(self, player_stats, opponent_stats):
        """
        Called at the start of each turn.
        
        Use for abilities that trigger at turn start.
        
        Args:
            player_stats (dict): Player's stats.
            opponent_stats (dict): Opponent's stats.
            
        Returns:
            list: Messages to display.
        """
        messages = []
        # Check for status effects that prevent action
        # (actual prevention happens in validate_action)
        return messages
    
    def on_turn_end(self, player_stats, opponent_stats):
        """
        Called at the end of each turn.
        
        Processes status effect damage (poison, burn, etc.) and
        decrements effect durations.
        
        Args:
            player_stats (dict): Player's stats.
            opponent_stats (dict): Opponent's stats.
            
        Returns:
            list: Messages to display.
        """
        messages = []
        
        # Process player status effects
        player_msgs = self.update_status_effects(player_stats)
        messages.extend(player_msgs)
        
        # Process opponent status effects
        opponent_msgs = self.update_status_effects(opponent_stats)
        messages.extend(opponent_msgs)
        
        return messages
    
    # ==================== STATE QUERIES ====================
    
    def is_battle_over(self, player_stats, opponent_stats):
        """
        Check if the battle is over.
        
        Args:
            player_stats (dict or CharacterStats): Player's stats.
            opponent_stats (dict or CharacterStats): Opponent's stats.
            
        Returns:
            bool: True if battle is over (someone fainted).
        """
        return self.check_victory_condition(player_stats, opponent_stats) != BATTLE_CONTINUES
    
    def get_available_moves(self, character, stats=None):
        """
        Get list of moves the character can currently use.
        
        Filters out moves that can't be used due to status effects, etc.
        
        Args:
            character (Character or str): Character instance or ID.
            stats (CharacterStats or dict, optional): Current battle stats.
            
        Returns:
            list[Move]: Available Move instances.
        """
        if isinstance(character, str):
            character = get_character(character)
        if not character:
            return []
        
        available = []
        for move_id in character.moves:
            move = get_move(move_id)
            if move:
                # Check if status prevents using this move
                if stats:
                    valid, _ = self.validate_action(move, stats, character)
                    if valid:
                        available.append(move)
                else:
                    available.append(move)
        
        return available
    
    def get_battle_state(self, player_stats, opponent_stats, turn_number=0):
        """
        Get a snapshot of the current battle state.
        
        Useful for UI display and debugging.
        
        Args:
            player_stats (dict or CharacterStats): Player's stats.
            opponent_stats (dict or CharacterStats): Opponent's stats.
            turn_number (int): Current turn number.
            
        Returns:
            dict: Battle state snapshot.
        """
        p_stats = player_stats.to_dict() if isinstance(player_stats, CharacterStats) else player_stats
        o_stats = opponent_stats.to_dict() if isinstance(opponent_stats, CharacterStats) else opponent_stats
        
        return {
            'turn': turn_number,
            'player_hp': p_stats.get('hp', 0),
            'player_max_hp': p_stats.get('max_hp', 100),
            'player_status': p_stats.get('status', 0),
            'player_effects': len(p_stats.get('status_effects', [])),
            'opponent_hp': o_stats.get('hp', 0),
            'opponent_max_hp': o_stats.get('max_hp', 100),
            'opponent_status': o_stats.get('status', 0),
            'opponent_effects': len(o_stats.get('status_effects', [])),
            'is_over': self.is_battle_over(p_stats, o_stats),
            'winner': self.check_victory_condition(p_stats, o_stats),
        }
    
    # ==================== VALIDATION ====================
    
    def validate_action(self, move, attacker_stats, character=None):
        """
        Validate if an action can be taken.
        
        Alias for validate_move() with clearer name.
        
        Args:
            move (Move or int): Move to validate.
            attacker_stats (dict or CharacterStats): Attacker's stats.
            character (Character, optional): Character using the move.
            
        Returns:
            tuple: (is_valid (bool), error_message (str or None))
        """
        return self.validate_move(move, attacker_stats, character)
    
class SimpleBattleRules(BattleRules):
    """
    Simplified battle rules for testing.
    
    Uses simpler damage calculation without crits or type effectiveness.
    Good for quick testing or simple game modes.
    """
    
    # Simpler damage formula
    BASE_DAMAGE_MULTIPLIER = 1.5
    CRIT_CHANCE = 0.0  # No crits in simple mode
    
    def calculate_damage(self, move, attacker_stats, defender_stats):
        """Simple damage calculation without crits."""
        if move.move_type == MOVE_TYPE_PHYSICAL:
            attack = attacker_stats.get('attack', 10)
            defense = defender_stats.get('defense', 10)
        else:
            attack = attacker_stats.get('attack', 10)
            defense = defender_stats.get('defense', 10)
        
        # Simple formula
        damage = (move.power * attack) / max(defense, 1)
        damage *= self.BASE_DAMAGE_MULTIPLIER
        
        return (max(self.MIN_DAMAGE, int(damage)), False)  # Never crits
    
    def apply_status_effect(self, effect_name, target_stats, target_obj=None):
        """No status effects in simple mode."""
        return {'success': False, 'reason': 'not_supported'}


# Optional global factory hook for engine-level rule replacement.
_BATTLE_RULES_FACTORY = None


def set_battle_rules_factory(factory):
    """
    Set a factory used by create_battle_rules().

    The factory can be a BattleRules subclass or any callable returning
    a BattleRules-compatible instance.
    """
    global _BATTLE_RULES_FACTORY
    if factory is not None and not callable(factory):
        raise TypeError("factory must be callable or None")
    _BATTLE_RULES_FACTORY = factory


def reset_battle_rules_factory():
    """Reset create_battle_rules() to use built-in BattleRules."""
    set_battle_rules_factory(None)


def create_battle_rules():
    """
    Build a BattleRules instance using the active factory override.
    """
    factory = _BATTLE_RULES_FACTORY or BattleRules
    rules = factory()
    if rules is None:
        raise ValueError("battle rules factory returned None")
    return rules
