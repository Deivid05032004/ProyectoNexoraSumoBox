"""Pure scheduling rules shared by configurable tournament brackets."""

from routers.competition import (
    _bracket_stage,
    _accumulate_group_results,
    _make_seeded_fixtures,
    _rank_group_standings,
    _round_robin_pairs,
    _unresolved_qualifying_ties,
    _phase_progress,
)


def test_round_robin_contains_every_pair_once_for_odd_and_even_groups():
    for team_count in range(2, 10):
        pairs = _round_robin_pairs(list(range(1, team_count + 1)))
        normalized = [frozenset(pair) for pair in pairs]
        assert len(pairs) == team_count * (team_count - 1) // 2
        assert len(set(normalized)) == len(normalized)
        assert all(len(pair) == 2 for pair in normalized)


def test_group_qualifiers_get_seeded_byes_and_cross_group_openers():
    teams = [
        {"team_id": 10 + index, "robot_id": 20 + index, "group_code": group}
        for index, group in enumerate(("NORTE", "SUR", "ESTE", "ESTE", "SUR", "NORTE"))
    ]
    fixtures, byes = _make_seeded_fixtures("QUARTERFINAL", teams, actor_id=1)

    assert _bracket_stage(6) == "QUARTERFINAL"
    assert len(fixtures) == 2
    assert len(byes) == 2
    assert len({team_id for _, _, pair, _ in fixtures for team_id in pair}) == 4
    teams_by_id = {team["team_id"]: team for team in teams}
    assert not any(
        teams_by_id[left]["group_code"] == teams_by_id[right]["group_code"]
        for _, _, (left, right), _ in fixtures
    )


def test_bracket_size_supports_the_configured_64_qualifier_ceiling():
    assert _bracket_stage(4) == "SEMIFINAL"
    assert _bracket_stage(8) == "QUARTERFINAL"
    assert _bracket_stage(16) == "ROUND_OF_16"
    assert _bracket_stage(32) == "ROUND_OF_32"
    assert _bracket_stage(64) == "ROUND_OF_64"
    assert _bracket_stage(65) == ""


def _standing(team_id, wins, yukos_for, yukos_against, group="A"):
    return {"team_id": team_id, "team": f"ROBOT {team_id}", "group_code": group,
            "wins": wins, "points": wins * 3, "yukos_for": yukos_for,
            "yukos_against": yukos_against}


def _result(left, right, winner, score_left=2, score_right=1, status="FINISHED", group="GROUP"):
    return {"stage_code": group, "status": status, "team_id_a": left,
            "team_id_b": right, "winner_team_id": winner,
            "score_a": score_left, "score_b": score_right}


def test_standings_prioritize_wins_over_yuko_difference():
    teams = [_standing(1, 2, 1, 8), _standing(2, 1, 20, 0)]
    ranked = _rank_group_standings(teams, [])
    assert [team["team_id"] for team in ranked] == [1, 2]
    assert [team["rank"] for team in ranked] == [1, 2]


def test_standings_use_yuko_difference_after_equal_wins():
    teams = [_standing(1, 2, 5, 2), _standing(2, 2, 8, 1)]
    ranked = _rank_group_standings(teams, [])
    assert [team["team_id"] for team in ranked] == [2, 1]


def test_head_to_head_resolves_equal_wins_and_yuko_difference():
    teams = [_standing(1, 2, 4, 2), _standing(2, 2, 4, 2)]
    ranked = _rank_group_standings(teams, [_result(1, 2, 2)])
    assert [team["team_id"] for team in ranked] == [2, 1]
    assert [team["rank"] for team in ranked] == [1, 2]
    assert all(team["tie_breaker"] == "HEAD_TO_HEAD" for team in ranked)


def test_head_to_head_never_overrides_different_win_totals():
    teams = [_standing(1, 2, 5, 2), _standing(2, 1, 5, 2)]
    ranked = _rank_group_standings(teams, [_result(2, 1, 2)])
    assert [team["team_id"] for team in ranked] == [1, 2]


def test_group_standings_ignore_other_groups():
    group_a = [_standing(1, 1, 2, 2), _standing(2, 1, 2, 2)]
    group_b_result = _result(1, 2, 1, group="QUARTERFINAL")
    ranked = _rank_group_standings(group_a, [group_b_result])
    assert [team["rank"] for team in ranked] == [1, 1]
    assert all(team["tie_status"] == "UNRESOLVED" for team in ranked)


def test_pending_cancelled_and_no_winner_fixtures_do_not_create_wins():
    stats = {team_id: {"team_id": team_id, "played": 0, "wins": 0, "losses": 0,
                       "points": 0, "yukos_for": 0, "yukos_against": 0}
             for team_id in (1, 2)}
    _accumulate_group_results(stats, [
        _result(1, 2, 1, 2, 1, status="SCHEDULED"),
        _result(1, 2, 1, 2, 0, status="CANCELLED"),
        _result(1, 2, None, 1, 1, status="FINISHED"),
    ])
    assert stats[1]["wins"] == stats[2]["wins"] == 0
    assert stats[1]["played"] == stats[2]["played"] == 1
    assert stats[1]["yukos_for"] == stats[2]["yukos_against"] == 1


def test_three_yuko_round_final_counts_one_combat_win_and_uses_final_yuko_total():
    stats = {team_id: {"team_id": team_id, "played": 0, "wins": 0, "losses": 0,
                       "points": 0, "yukos_for": 0, "yukos_against": 0}
             for team_id in (1, 2)}
    _accumulate_group_results(stats, [_result(1, 2, 1, score_left=2, score_right=1)])
    assert stats[1]["wins"] == 1
    assert stats[1]["points"] == 3
    assert (stats[1]["yukos_for"] - stats[1]["yukos_against"]) == 1
    assert stats[2]["wins"] == 0


def test_unresolved_two_team_tie_without_valid_direct_meeting_stays_tied():
    teams = [_standing(1, 2, 4, 2), _standing(2, 2, 4, 2)]
    ranked = _rank_group_standings(teams, [_result(1, 2, 1, status="CANCELLED")])
    assert [team["rank"] for team in ranked] == [1, 1]
    assert all(team["tie_status"] == "UNRESOLVED" for team in ranked)


def test_transitive_complete_multi_team_head_to_head_resolves_tie():
    teams = [_standing(1, 2, 4, 4), _standing(2, 2, 4, 4), _standing(3, 2, 4, 4)]
    matches = [_result(1, 2, 1), _result(1, 3, 1), _result(2, 3, 2)]
    ranked = _rank_group_standings(teams, matches)
    assert [team["team_id"] for team in ranked] == [1, 2, 3]
    assert [team["rank"] for team in ranked] == [1, 2, 3]


def test_cyclic_multi_team_direct_results_remain_an_explicit_tie():
    teams = [_standing(1, 2, 4, 4), _standing(2, 2, 4, 4), _standing(3, 2, 4, 4)]
    matches = [_result(1, 2, 1), _result(2, 3, 2), _result(3, 1, 3)]
    ranked = _rank_group_standings(teams, matches)
    assert [team["rank"] for team in ranked] == [1, 1, 1]
    assert all(team["tie_status"] == "UNRESOLVED" for team in ranked)


def test_unresolved_tie_at_qualification_boundary_blocks_advancement():
    groups = {
        "A": [_standing(1, 2, 4, 4), _standing(2, 2, 4, 4), _standing(3, 1, 2, 5)],
        "B": [_standing(4, 3, 7, 2), _standing(5, 2, 5, 4), _standing(6, 1, 2, 6)],
    }
    for rows in groups.values():
        _rank_group_standings(rows, [])
    assert _unresolved_qualifying_ties(groups) == ["A"]


def test_unresolved_tie_below_top_two_does_not_block_qualification():
    rows = [_standing(1, 3, 7, 2), _standing(2, 2, 5, 4),
            _standing(3, 1, 3, 6), _standing(4, 1, 3, 6)]
    _rank_group_standings(rows, [])
    assert rows[2]["rank"] == rows[3]["rank"] == 3
    assert _unresolved_qualifying_ties({"A": rows}) == []


def test_phase_progress_counts_live_and_scheduled_bouts_until_every_result_is_final():
    matches = [_result(1, 2, 1), _result(3, 4, None, status="SCHEDULED"),
               _result(5, 6, None, status="LIVE"),
               _result(7, 8, None, status="CANCELLED")]
    progress = _phase_progress(matches, "GROUP")
    assert progress == {"stage": "GROUP", "total": 4, "finished": 1, "live": 1,
                        "scheduled": 1, "cancelled": 1, "remaining": 3, "complete": False}


def test_finished_tournament_snapshot_counts_final_phase_as_complete():
    final_match = _result(1, 2, 1)
    final_match["stage_code"] = "FINAL"
    progress = _phase_progress([final_match], "FINISHED")
    assert progress["stage"] == "FINAL"
    assert progress["complete"] is True


def test_updated_official_direct_result_reorders_the_standings():
    teams = [_standing(1, 1, 2, 2), _standing(2, 1, 2, 2)]
    matches = [_result(1, 2, 1)]
    assert _rank_group_standings(teams, matches)[0]["team_id"] == 1
    matches[0]["winner_team_id"] = 2
    assert _rank_group_standings(teams, matches)[0]["team_id"] == 2


def test_duplicate_head_to_head_fixtures_do_not_pick_an_arbitrary_winner():
    teams = [_standing(1, 2, 4, 2), _standing(2, 2, 4, 2)]
    matches = [_result(1, 2, 1), _result(1, 2, 1)]
    ranked = _rank_group_standings(teams, matches)
    assert [team["rank"] for team in ranked] == [1, 1]
    assert all(team["tie_status"] == "UNRESOLVED" for team in ranked)
