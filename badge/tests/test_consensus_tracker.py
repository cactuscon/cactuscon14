"""Behavior tests for consensus tracker determinism and mismatch handling."""

from cactuscon.game.engine.consensus import (
    CONSENSUS_AGREED,
    CONSENSUS_FAILED,
    ConsensusTracker,
    TurnOutcome,
)


def test_consensus_tracker_is_deterministic_and_rejects_mismatch():
    token = b"0123456789abcdef"
    tracker_a = ConsensusTracker(token)
    tracker_b = ConsensusTracker(token)

    rng_a = tracker_a.begin_turn(0, 1, 2)
    rng_b = tracker_b.begin_turn(0, 1, 2)
    assert [rng_a.random(), rng_a.random()] == [rng_b.random(), rng_b.random()]

    outcome_a = TurnOutcome()
    outcome_b = TurnOutcome()
    for outcome in (outcome_a, outcome_b):
        outcome.turn_number = 0
        outcome.player_move_id = 1
        outcome.opponent_move_id = 2
        outcome.player_damage_dealt = 10
        outcome.opponent_damage_dealt = 8
        outcome.player_hp_after = 90
        outcome.opponent_hp_after = 92

    tracker_a.record_outcome(outcome_a)
    tracker_b.record_outcome(outcome_b)
    hash_a = tracker_a.get_our_hash()
    hash_b = tracker_b.get_our_hash()
    assert hash_a == hash_b
    assert tracker_a.receive_opponent_hash(hash_b) == CONSENSUS_AGREED
    assert tracker_b.receive_opponent_hash(hash_a) == CONSENSUS_AGREED
    tracker_a.commit_turn()
    tracker_b.commit_turn()

    tracker_c = ConsensusTracker(token)
    tracker_c.begin_turn(0, 1, 2)
    mismatched = TurnOutcome()
    mismatched.turn_number = 0
    mismatched.player_move_id = 1
    mismatched.opponent_move_id = 2
    mismatched.player_damage_dealt = 999
    tracker_c.record_outcome(mismatched)
    assert tracker_c.receive_opponent_hash(hash_a) == CONSENSUS_FAILED
