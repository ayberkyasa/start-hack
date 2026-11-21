import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.domain.records import Run
from app.settings import load_settings
from app.storage.database import open_database
from app.storage.records import ModelUsage


class ModelUsageTests(unittest.TestCase):
    def test_outcomes_and_cost_survive_database_reopen(self):
        stamp = "2026-11-21T09:00:00Z"
        config = load_settings({}).freeze(scenario_id="library", code_revision="demo")
        run = Run(run_id="demo", configuration=config, phase="preparing", created_at=stamp)
        base = dict(run_id=run.run_id, recorded_at=stamp, provider_id="mock",
                    model_id="demo", duration_ms=125)
        records = [ModelUsage(usage_id="legacy", **base)]
        for outcome in ("completed", "refused", "incomplete", "error"):
            records.append(ModelUsage(usage_id=outcome, outcome=outcome, **base))
        records.append(ModelUsage(usage_id="free", outcome="completed", input_tokens=4,
                                  output_tokens=2, estimated_usd_micros=0,
                                  pricing_version="mock-free", **base))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "usage.sqlite3"
            with open_database(path) as repo:
                repo.insert(run, *records)
            with open_database(path) as repo:
                for record in records:
                    with self.subTest(usage_id=record.usage_id):
                        self.assertEqual(repo.get(ModelUsage, record.usage_id), record)

    def test_older_json_has_unknown_outcome_and_cost(self):
        row = ModelUsage.model_validate_json(
            '{"usage_id":"old","run_id":"demo","recorded_at":"2026-11-21T09:00:00Z",'
            '"provider_id":"mock","model_id":"demo","duration_ms":125}'
        )
        self.assertIsNone(row.outcome)
        self.assertIsNone(row.estimated_usd_micros)
