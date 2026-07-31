from __future__ import annotations

import unittest

from csv_cleaner.core.validator import is_valid_email, parse_date_value


class ValidatorTests(unittest.TestCase):
    def test_valid_email(self) -> None:
        self.assertTrue(is_valid_email("anna@example.com"))

    def test_invalid_emails(self) -> None:
        for value in ("anna example.com", "anna@", "anna@example", "@example.com"):
            with self.subTest(value=value):
                self.assertFalse(is_valid_email(value))

    def test_date_parser(self) -> None:
        parsed = parse_date_value("31.01.2026 14:30")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.year, 2026)
