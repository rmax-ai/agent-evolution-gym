"""Validation of unique scenario/seed allocations within one split."""

import pytest

from agentgym.core.splits import SplitSpec


def test_split_spec_rejects_duplicate_pairs_across_entries() -> None:
    with pytest.raises(ValueError, match=r"duplicate \(scenario_id, seed\).*'edit_page'.*1100"):
        SplitSpec(
            entries=[
                {"scenario_id": "edit_page", "count": 1, "seeds": [1100]},
                {"scenario_id": "edit_page", "count": 1, "seeds": [1100]},
            ]
        )


def test_split_spec_allows_same_seed_for_different_scenarios() -> None:
    split = SplitSpec(
        entries=[
            {"scenario_id": "edit_page", "count": 1, "seeds": [1100]},
            {"scenario_id": "retrieval", "count": 1, "seeds": [1100]},
        ]
    )

    assert list(split.iter_seeded()) == [("edit_page", 1100), ("retrieval", 1100)]
