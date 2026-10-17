from routers.competition import can_transition, rank_rows


def test_competition_lifecycle_allows_only_documented_transitions():
    assert can_transition("DRAFT", "SCHEDULED")
    assert can_transition("LIVE", "PAUSED")
    assert can_transition("PAUSED", "LIVE")
    assert can_transition("FINISHED", "FINISHED")
    assert not can_transition("FINISHED", "LIVE")
    assert not can_transition("CANCELLED", "SCHEDULED")


def test_leaderboard_preserves_ties_and_ranks_categories_independently():
    rows = [
        {"category_id": 1, "team_id": 4, "points": 10},
        {"category_id": 1, "team_id": 2, "points": 10},
        {"category_id": 1, "team_id": 9, "points": 7},
        {"category_id": 2, "team_id": 3, "points": 7},
    ]
    assert [row["rank"] for row in rank_rows(rows)] == [1, 1, 2, 1]
