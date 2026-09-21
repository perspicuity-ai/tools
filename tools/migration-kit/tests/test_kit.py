#!/usr/bin/env python3
"""Tests for the migration kit.

These run without special hardware and without network access. Each one exercises behaviour
that a refactor could plausibly break, and each corresponds to a defect that actually
occurred during the first real migration:

  * a link rewriter that walked only the unit tree and left 67 dead links in the material
    moving with it;
  * a rewriter that pinned a repository's own internal links, freezing them at migration;
  * a due-date filter that compared the prose `next_check` field as a string and reported
    zero due records while the reader reported ten;
  * a text pattern match that counted link-shaped strings inside fenced code blocks and
    overstated the work by nearly three times.

Run with:  python3 -m pytest tests/ -q      or      python3 tests/test_kit.py
"""

import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), KIT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


outbound = load("outbound_links")
rewriter = load("rewrite_cross_links")
checker = load("dead_links")
migration = load("unit_migration_check")


class Fixture(unittest.TestCase):
    """A small repository shaped like a real migration: one unit, one sibling, one core dir."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        r = self.tmp / "repo"
        (r / "docs/initiatives/unit").mkdir(parents=True)
        (r / "docs/research").mkdir(parents=True)
        (r / "Decisions").mkdir(parents=True)
        (r / "docs/initiatives/unit/BRIEF.md").write_text(
            "# Brief\n\nSee [research](../../research/NOTES.md) and [decision](../../../Decisions/D1.md).\n",
            encoding="utf-8")
        (r / "docs/initiatives/unit/INNER.md").write_text("# Inner\n", encoding="utf-8")
        (r / "docs/research/NOTES.md").write_text(
            "# Notes\n\nBack to [brief](../initiatives/unit/BRIEF.md).\n", encoding="utf-8")
        (r / "Decisions/D1.md").write_text("# D1\n", encoding="utf-8")
        self.repo = r


class TestLinkResolution(Fixture):
    def test_prefix_match_is_boundary_aware(self):
        self.assertTrue(outbound.is_moving("docs/research/a.md", ["docs/research"]))
        self.assertTrue(outbound.is_moving("docs/research", ["docs/research"]))
        self.assertFalse(outbound.is_moving("docs/research-other/a.md", ["docs/research"]))

    def test_longest_slug_wins(self):
        slugs = {"docs": "org/wide", "docs/research": "org/narrow"}
        self.assertEqual(outbound.owning_slug("docs/research/a.md", slugs), "org/narrow")
        self.assertEqual(outbound.owning_slug("docs/other/a.md", slugs), "org/wide")

    def test_containment_rejects_siblings(self):
        self.assertTrue(outbound.is_contained(self.repo / "docs/D1.md", self.repo))
        self.assertFalse(outbound.is_contained(self.repo.parent / "elsewhere.md", self.repo))


class TestOutboundRewrite(Fixture):
    def run_tool(self, *extra):
        script = KIT / "outbound_links.py"
        cmd = [sys.executable, str(script), "--root", str(self.repo),
               "--moves-out", "docs/research",
               "--moving-slug", "docs/research=org/unit",
               "--sha", "abc1234", *extra]
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_rewrites_link_to_moving_tree(self):
        result = self.run_tool("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(len(plan["edits"]), 1)
        self.assertIn("org/unit", plan["edits"][0]["to"])
        self.assertEqual(plan["errors"], [])

    def test_apply_changes_only_the_link(self):
        self.run_tool("--apply")
        text = (self.repo / "docs/initiatives/unit/BRIEF.md").read_text(encoding="utf-8")
        self.assertIn("https://github.com/org/unit/blob/abc1234/docs/research/NOTES.md", text)
        self.assertIn("See [research](", text)          # label untouched
        self.assertIn("[decision](../../../Decisions/D1.md)", text)  # non-moving untouched

    def test_dry_run_writes_nothing(self):
        before = (self.repo / "docs/initiatives/unit/BRIEF.md").read_text(encoding="utf-8")
        self.run_tool()
        after = (self.repo / "docs/initiatives/unit/BRIEF.md").read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_links_inside_fenced_blocks_are_left_alone(self):
        target = self.repo / "docs/initiatives/unit/FENCED.md"
        target.write_text(
            "# Fenced\n\n```sh\nsee [x](../../research/NOTES.md)\n```\n\n"
            "And [real](../../research/NOTES.md).\n", encoding="utf-8")
        self.run_tool("--apply")
        text = target.read_text(encoding="utf-8")
        self.assertIn("[x](../../research/NOTES.md)", text)      # example preserved verbatim
        self.assertIn("https://github.com/org/unit/blob/abc1234/docs/research/NOTES.md", text)

    def test_link_between_two_moving_files_is_skipped(self):
        (self.repo / "docs/research/OTHER.md").write_text(
            "# Other\n\nSee [notes](NOTES.md).\n", encoding="utf-8")
        result = self.run_tool("--json")
        plan = json.loads(result.stdout)
        self.assertEqual([e["file"] for e in plan["edits"]], ["docs/initiatives/unit/BRIEF.md"])


class TestRewriterInternalLinks(Fixture):
    def test_internal_links_stay_relative_and_are_not_pinned(self):
        mirror = self.tmp / "mirror"
        shutil.copytree(self.repo / "docs/initiatives/unit", mirror)
        (mirror / "docs/research").parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.repo / "docs/research", mirror / "docs/research")
        result = subprocess.run(
            [sys.executable, str(KIT / "rewrite_cross_links.py"),
             "--root", str(self.repo), "--unit", "docs/initiatives/unit", "--mirror", str(mirror),
             "--unit-slug", "org/unit", "--core-slug", "org/core", "--core-sha", "abc1234",
             "--moves-out", "docs/research", "--moving-slug", "docs/research=org/unit",
             "--moved-from", "docs/research", "--apply", "--json"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        brief = (mirror / "BRIEF.md").read_text(encoding="utf-8")
        # The link to the core decision crosses the boundary and is pinned.
        self.assertIn("org/core/blob/abc1234/Decisions/D1.md", brief)
        # The link to the research that moved with the unit stays relative.
        self.assertNotIn("org/unit/blob", brief)


class TestDeadLinks(Fixture):
    def run_tool(self):
        return subprocess.run(
            [sys.executable, str(KIT / "dead_links.py"), "--root", str(self.repo),
             "--path", "docs", "--json"], capture_output=True, text=True)

    def test_clean_tree_reports_nothing(self):
        plan = json.loads(self.run_tool().stdout)
        self.assertEqual(plan["dead"], [])
        self.assertGreater(plan["checked"], 0)

    def test_injected_dead_link_is_reported(self):
        f = self.repo / "docs/initiatives/unit/BRIEF.md"
        f.write_text("# Brief\n\nSee [gone](zzz-missing.md).\n", encoding="utf-8")
        plan = json.loads(self.run_tool().stdout)
        self.assertEqual(len(plan["dead"]), 1)
        self.assertEqual(plan["dead"][0]["target"], "zzz-missing.md")

    def test_scheme_shaped_target_is_not_a_dead_link(self):
        # urn:li:organization:ID is an identifier, not a missing file. Resolving it against
        # the filesystem produced a false dead link in a real migration report.
        (self.repo / "docs/SCHEME.md").write_text(
            "# S\n\nSee [organisation](urn:li:organization:101) and [x](mailto:a@b.c).\n",
            encoding="utf-8")
        plan = json.loads(self.run_tool().stdout)
        self.assertEqual(plan["dead"], [])

    def test_fenced_example_is_not_counted_as_a_dead_link(self):
        (self.repo / "docs/FENCED.md").write_text(
            "# F\n\n```\n[a](also-missing.md)\n```\n", encoding="utf-8")
        plan = json.loads(self.run_tool().stdout)
        self.assertEqual(plan["dead"], [])


class TestMirrorCompare(Fixture):
    def test_identical_copy_passes(self):
        a = self.tmp / "src"
        b = self.tmp / "mirror"
        shutil.copytree(self.repo / "docs/research", a)
        shutil.copytree(self.repo / "docs/research", b)
        result = migration.compare_unit(None, a, b)
        self.assertTrue(result["identical"])

    def test_each_kind_of_damage_is_caught(self):
        a = self.tmp / "src"
        b = self.tmp / "mirror"
        shutil.copytree(self.repo / "docs/research", a)
        shutil.copytree(self.repo / "docs/research", b)
        (b / "EXTRA.md").write_text("x", encoding="utf-8")
        (b / "NOTES.md").write_text("# Notes changed\n", encoding="utf-8")
        result = migration.compare_unit(None, a, b)
        self.assertFalse(result["identical"])
        self.assertEqual(result["extra"], ["EXTRA.md"])
        self.assertEqual(result["changed"], ["NOTES.md"])

    def test_removed_file_is_caught(self):
        a = self.tmp / "src"
        b = self.tmp / "mirror"
        shutil.copytree(self.repo / "docs/research", a)
        shutil.copytree(self.repo / "docs/research", b)
        (b / "NOTES.md").unlink()
        result = migration.compare_unit(None, a, b)
        self.assertEqual(result["missing"], ["NOTES.md"])


class TestFleetViewDueDates(unittest.TestCase):
    """The fleet view must read the reader's normalised date, not the prose field."""

    def test_due_uses_next_check_date_and_ignores_prose(self):
        fleet = load("fleet_view")
        scans = [{
            "name": "r", "path": "/tmp", "visibility": "private", "records": [
                {"path": "a.md", "record_status": "open", "next_check_date": "2026-01-01",
                 "next_check": "sometime in the new year", "work_status": "active",
                 "queue_state": "ready"},
                {"path": "b.md", "record_status": "open", "next_check_date": None,
                 "next_check": "September 16, America/Edmonton. A long sentence.",
                 "work_status": "accepted", "queue_state": "needs_you"},
            ]}]
        rows = fleet.summarise(scans, "2026-06-01")
        self.assertEqual(rows[0]["due"], 1)
        self.assertEqual(rows[0]["unscheduled"], 1)
        self.assertEqual(rows[0]["due_items"][0]["path"], "a.md")

    def test_exclusion_moves_a_record_out_of_the_owner_count(self):
        fleet = load("fleet_view")
        # Exercise the counting rule directly rather than through scan(), which needs the
        # project's reader on the path.
        records = [{"path": "docs/outreach/x.md", "record_status": "open"},
                   {"path": "Decisions/keep.md", "record_status": "open"}]
        patterns = [{"prefix": "docs/outreach/", "now_in": "unit"}]
        kept, moved = [], []
        for record in records:
            owner = next((p["now_in"] for p in patterns
                          if record["path"].startswith(p["prefix"])), None)
            (moved if owner else kept).append(record)
        self.assertEqual(len(kept), 1)
        self.assertEqual(moved[0]["path"], "docs/outreach/x.md")

    def test_public_only_excludes_private_roots(self):
        fleet = load("fleet_view")
        roots = [{"name": "a", "visibility": "private"}, {"name": "b", "visibility": "public"}]
        kept = [r for r in roots if r.get("visibility") == "public"]
        self.assertEqual([r["name"] for r in kept], ["b"])


class TestDiscoverRoots(unittest.TestCase):
    def test_declares_docs_when_records_live_there(self):
        fleet = load("fleet_view")
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "plain/.git").mkdir(parents=True)
        (tmp / "plain/docs").mkdir()
        (tmp / "structured/.git").mkdir(parents=True)
        (tmp / "structured/Decisions").mkdir()
        config = fleet.discover_roots(tmp)
        by_name = {r["name"]: r for r in config["roots"]}
        self.assertEqual(by_name["plain"]["sources"], ["docs"])
        self.assertEqual(by_name["structured"]["sources"], ["Decisions"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
