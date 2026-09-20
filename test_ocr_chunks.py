import unittest

import fitz

from grader import identify_pages


class ChunkedIdentificationTests(unittest.TestCase):
    def test_page_ranges_keep_original_page_numbers(self):
        document = fitz.open()
        for number in range(7):
            page = document.new_page()
            page.insert_text((36, 36), f"Student {number}")
        pdf_bytes = document.tobytes()
        document.close()

        matches = [
            *identify_pages(pdf_bytes, [], 0, 4),
            *identify_pages(pdf_bytes, [], 4, 8),
        ]
        self.assertEqual([match.page_index for match in matches], list(range(7)))
        self.assertEqual(matches[-1].ocr_text, "Student 6")


if __name__ == "__main__":
    unittest.main()
