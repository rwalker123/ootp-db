"""Tests for MCP read-only SQL validation."""

import sys
from pathlib import Path as P

_SRC = P(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import unittest

from ootp_mcp.sql_validate import clamp_limit_in_sql, validate_readonly_sql


class TestValidateReadonlySql(unittest.TestCase):
    def test_select_ok(self):
        self.assertEqual(
            validate_readonly_sql("SELECT 1"),
            "SELECT 1",
        )

    def test_with_select_ok(self):
        s = validate_readonly_sql("WITH x AS (SELECT 1 AS a) SELECT a FROM x")
        self.assertTrue(s.upper().startswith("WITH"))

    def test_reject_multi_statement(self):
        with self.assertRaises(ValueError):
            validate_readonly_sql("SELECT 1; SELECT 2")

    def test_allow_semicolon_in_string_literal(self):
        s = validate_readonly_sql("SELECT ';' AS semi")
        self.assertEqual(s, "SELECT ';' AS semi")

    def test_allow_semicolon_in_line_comment(self):
        s = validate_readonly_sql("SELECT 1 -- ; semicolon inside comment")
        self.assertEqual(s, "SELECT 1 -- ; semicolon inside comment")

    def test_allow_semicolon_in_block_comment(self):
        s = validate_readonly_sql("SELECT 1 /* ; semicolon inside comment */")
        self.assertEqual(s, "SELECT 1 /* ; semicolon inside comment */")

    def test_reject_string_semicolon_then_second_statement(self):
        with self.assertRaises(ValueError):
            validate_readonly_sql("SELECT ';' AS semi; SELECT 2")

    def test_reject_insert(self):
        with self.assertRaises(ValueError):
            validate_readonly_sql("INSERT INTO t VALUES (1)")

    def test_reject_delete(self):
        with self.assertRaises(ValueError):
            validate_readonly_sql("DELETE FROM players")

    def test_reject_not_select(self):
        with self.assertRaises(ValueError):
            validate_readonly_sql("UPDATE players SET x=1")

    def test_reject_writable_cte_delete(self):
        with self.assertRaises(ValueError):
            validate_readonly_sql(
                "WITH x AS (DELETE FROM players RETURNING player_id) "
                "SELECT player_id FROM x"
            )

    def test_reject_writable_cte_update(self):
        with self.assertRaises(ValueError):
            validate_readonly_sql(
                "WITH u AS (UPDATE players SET age = age RETURNING player_id) "
                "SELECT player_id FROM u"
            )


class TestClampLimit(unittest.TestCase):
    def test_appends_limit(self):
        self.assertEqual(
            clamp_limit_in_sql("SELECT 1", 100).upper(),
            "SELECT 1 LIMIT 100",
        )

    def test_skips_if_limit_present(self):
        self.assertEqual(
            clamp_limit_in_sql("SELECT 1 LIMIT 5", 100),
            "SELECT 1 LIMIT 5",
        )


if __name__ == "__main__":
    unittest.main()
