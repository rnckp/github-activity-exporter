"""Regression tests for repository owner selection and exports."""

import csv
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "01_get_activity.py"
spec = importlib.util.spec_from_file_location("get_activity", SCRIPT)
activity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activity)


class ExportTests(unittest.TestCase):
    def test_default_exports_personal_activity_with_or_without_organizations(self) -> None:
        for orgs in ([], ["example-org"]):
            with self.subTest(orgs=orgs):
                self.check_export(orgs, [], ["user:example", *[f"org:{o}" for o in orgs]])

    def test_explicit_organization_does_not_require_membership_discovery(self) -> None:
        self.check_export([], ["--org", "example-org"], ["org:example-org"])

    def check_export(self, orgs: list[str], args: list[str], expected_scopes: list[str]) -> None:
        queries: list[str] = []

        def paginate(
            path: str, params: dict | None = None, items_key: str | None = None
        ) -> list[dict]:
            if path == "/user/memberships/orgs":
                self.assertFalse(args, "Explicit --org must skip membership discovery")
                return [{"organization": {"login": org}} for org in orgs]
            query = params["q"]
            queries.append(query)
            owner = query.split()[0].split(":")[1]
            if path == "/search/commits":
                return [
                    {
                        "sha": f"{owner}-sha",
                        "repository": {"full_name": f"{owner}/project"},
                        "commit": {"message": "Example commit", "author": {"date": "2026-02-01"}},
                        "html_url": f"https://github.com/{owner}/project/commit/example",
                    }
                ]
            return [
                {
                    "number": 1,
                    "title": "Example issue or PR",
                    "repository_url": f"https://api.github.com/repos/{owner}/project",
                    "html_url": f"https://github.com/{owner}/project/issues/1",
                }
            ]

        with tempfile.TemporaryDirectory() as directory:
            prefix = str(Path(directory) / "activity")
            argv = [
                str(SCRIPT),
                "--from",
                "2026-01-01",
                "--to",
                "2026-12-31",
                "--out",
                prefix,
                *args,
            ]
            with (
                patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}),
                patch("sys.argv", argv),
                patch.object(activity.GitHubClient, "me", return_value={"login": "example"}),
                patch.object(activity.GitHubClient, "paginate", side_effect=paginate),
            ):
                self.assertEqual(activity.main(), 0)

            self.assertEqual(len(queries), 7 * len(expected_scopes))
            self.assertEqual({q.split()[0] for q in queries}, set(expected_scopes))
            self.assertTrue(all("2026-01-01..2026-12-31" in q for q in queries))
            records = json.loads(Path(f"{prefix}_2026-01-01_2026-12-31.json").read_text())
            self.assertEqual(len(records), 7 * len(expected_scopes))
            self.assertEqual(
                {r["org"] for r in records}, {s.split(":")[1] for s in expected_scopes}
            )
            with Path(f"{prefix}_2026-01-01_2026-12-31.csv").open(newline="") as file:
                self.assertEqual(len(list(csv.DictReader(file))), len(records))
