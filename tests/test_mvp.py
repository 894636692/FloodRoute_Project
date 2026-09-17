import unittest

from config import Config
from data import build_demo_city, make_observed_data
from model import calculate_scores, plan_route, route_metrics, should_replan


class MvpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config()
        self.city = build_demo_city(
            self.config.width,
            self.config.height,
            self.config.random_seed,
        )

    def test_route_reaches_goal(self) -> None:
        observed = make_observed_data(self.city, 0)
        scores = calculate_scores(self.city, observed, self.config)
        path = plan_route(
            self.city,
            self.config.start,
            self.config.goal,
            scores,
            "shortest",
            self.config,
        )
        self.assertEqual(path[0], self.config.start)
        self.assertEqual(path[-1], self.config.goal)

    def test_risk_route_can_differ_from_shortest_route(self) -> None:
        observed = make_observed_data(self.city, 0)
        scores = calculate_scores(self.city, observed, self.config)
        shortest = plan_route(
            self.city,
            self.config.start,
            self.config.goal,
            scores,
            "shortest",
            self.config,
        )
        risk = plan_route(
            self.city,
            self.config.start,
            self.config.goal,
            scores,
            "risk",
            self.config,
        )
        self.assertNotEqual(shortest, risk)

    def test_stale_information_triggers_replanning(self) -> None:
        observed = make_observed_data(self.city, 120)
        scores = calculate_scores(self.city, observed, self.config)
        risk_path = plan_route(
            self.city,
            self.config.start,
            self.config.goal,
            scores,
            "risk",
            self.config,
        )
        trigger, _, _ = should_replan(risk_path, scores, self.config)
        self.assertTrue(trigger)

    def test_trusted_route_reduces_true_risk_when_data_is_stale(self) -> None:
        observed = make_observed_data(self.city, 120)
        truth = make_observed_data(self.city, 0)
        observed_scores = calculate_scores(self.city, observed, self.config)
        truth_scores = calculate_scores(self.city, truth, self.config)

        risk_path = plan_route(
            self.city,
            self.config.start,
            self.config.goal,
            observed_scores,
            "risk",
            self.config,
        )
        trusted_path = plan_route(
            self.city,
            self.config.start,
            self.config.goal,
            observed_scores,
            "trusted",
            self.config,
        )

        risk_metrics = route_metrics(risk_path, observed_scores, truth_scores)
        trusted_metrics = route_metrics(trusted_path, observed_scores, truth_scores)
        self.assertLess(trusted_metrics["true_risk"], risk_metrics["true_risk"])


if __name__ == "__main__":
    unittest.main()
