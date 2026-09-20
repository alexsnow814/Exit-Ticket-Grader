import unittest
from types import SimpleNamespace

from scan_index import (
    INDEX_HEADERS, file_is_complete, indexed_prefix, parse_index, rows_for_pages,
)


class ScanIndexTests(unittest.TestCase):
    def test_new_file_does_not_invalidate_existing_file(self):
        old_version = ("old-id", "2026-09-18T12:00:00Z", "123")
        new_version = ("new-id", "2026-09-19T12:00:00Z", "456")
        values = [INDEX_HEADERS, *rows_for_pages(
            "1.1 Exit Ticket", "old.pdf", old_version, 2,
            [SimpleNamespace(page_index=0, ocr_text="Ada"),
             SimpleNamespace(page_index=1, ocr_text="Ben")],
        )]
        index = parse_index(values)
        self.assertTrue(file_is_complete(index, old_version))
        self.assertFalse(file_is_complete(index, new_version))
        self.assertEqual([p.header_text for p in indexed_prefix(index, old_version)],
                         ["Ada", "Ben"])

    def test_partial_file_resumes_and_changed_version_restarts(self):
        version = ("file-id", "first-edit", "123")
        values = [INDEX_HEADERS, *rows_for_pages(
            "1.1 Exit Ticket", "scan.pdf", version, 3,
            [SimpleNamespace(page_index=0, ocr_text="Ada")],
        )]
        index = parse_index(values)
        self.assertEqual(len(indexed_prefix(index, version)), 1)
        self.assertFalse(file_is_complete(index, version))
        self.assertEqual(indexed_prefix(index, ("file-id", "new-edit", "123")), [])

    def test_rejects_incorrect_headers(self):
        with self.assertRaises(ValueError):
            parse_index([["wrong header"]])

    def test_legacy_eight_column_index_and_saved_assignment(self):
        version = ("file-id", "revision", "123")
        row = rows_for_pages("1.11 Exit Ticket", "scan.pdf", version, 1, [
            SimpleNamespace(page_index=0, ocr_text="Extra")
        ])[0]
        legacy = parse_index([INDEX_HEADERS[:8], row[:8]])
        self.assertEqual(indexed_prefix(legacy, version)[0].assigned_student, "")
        saved = parse_index([INDEX_HEADERS, [*row[:8], "Livia Bento Pereira"]])
        self.assertEqual(indexed_prefix(saved, version)[0].assigned_student,
                         "Livia Bento Pereira")


if __name__ == "__main__":
    unittest.main()
