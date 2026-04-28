import sys
import unittest
from pathlib import Path
from types import ModuleType


def fake_module(name, **attrs):
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


sys.modules["helpers"] = fake_module(
    "helpers",
    fetchall=lambda *args, **kwargs: [],
    with_psycopg=lambda fn: fn(None, None),
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import medals


class MedalEligibilityTests(unittest.TestCase):
    def test_medal_candidate_queries_exclude_knocked_out_challengers(self):
        query_functions = [
            (medals.highest_tier_week, (10,)),
            (medals.highest_tier_challenge, (1,)),
            (medals.earliest_for_challenge, (1,)),
            (medals.earliest_for_week, (10,)),
            (medals.latest_for_challenge, (1,)),
            (medals.latest_for_week, (10,)),
            (medals.gold, (10,)),
            (medals.green, (10,)),
            (medals.red, (10,)),
            (medals.diamond, (10,)),
            (medals.first_to_green, (10,)),
            (medals.all_gold_challenge, (1,)),
            (medals.all_green_challenge, (1,)),
        ]

        for query_function, args in query_functions:
            with self.subTest(query=query_function.__name__):
                sql, _ = query_function(*args)
                self.assertIn("JOIN challenger_challenges cc", sql)
                self.assertIn("cc.knocked_out = false", sql)

    def test_reconcile_medals_allows_no_eligible_candidates(self):
        self.assertEqual(medals.reconcile_medals([], []), [])


if __name__ == "__main__":
    unittest.main()
