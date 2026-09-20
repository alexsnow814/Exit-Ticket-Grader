import unittest
from types import SimpleNamespace
from unittest.mock import patch

import fitz

import grader


class NameCropTests(unittest.TestCase):
    def setUp(self):
        document = fitz.open()
        page = document.new_page(width=1000, height=1000)
        page.insert_text((50, 75), "Name: Jane Smith")
        page.insert_text((50, 130), "Question: Jane Smith")
        self.pdf_bytes = document.tobytes()
        document.close()

    def test_embedded_text_stops_before_question(self):
        text = grader.extract_page_text(self.pdf_bytes, 0)
        self.assertIn("Name: Jane Smith", text)
        self.assertNotIn("Question:", text)

    def test_scanned_name_uses_eleven_percent_of_page(self):
        document = fitz.open()
        document.new_page(width=1000, height=1000)
        pdf_bytes = document.tobytes()
        document.close()
        shapes = []

        def recognize(image):
            shapes.append(image.shape)
            return SimpleNamespace(txts=["Name: Jane Smith"])

        with patch.object(grader, "_ocr_engine", return_value=recognize):
            matches = grader.identify_pages(pdf_bytes, ["Jane Smith"])
        self.assertEqual(matches[0].student, "Jane Smith")
        self.assertEqual(len(shapes), 1)
        self.assertEqual(shapes[0][0], 154)

    def test_uncertain_name_retries_wider_area(self):
        with patch.object(grader, "_extract_header_text", side_effect=[
            "Name: NadirAlAsadh", "Name: Nadir Al-Asadi",
        ]) as extract:
            matches = grader.identify_pages(self.pdf_bytes, ["Nadir Al-Asadi"])
        self.assertEqual(matches[0].student, "Nadir Al-Asadi")
        self.assertEqual(matches[0].ocr_text, "Name: Nadir Al-Asadi")
        self.assertEqual(extract.call_count, 2)

    def test_extra_does_not_retry_or_assign_a_student(self):
        with patch.object(grader, "_extract_header_text", return_value="Name: Extra") as extract:
            matches = grader.identify_pages(self.pdf_bytes, ["Jane Smith"])
        self.assertIsNone(matches[0].student)
        self.assertEqual(extract.call_count, 1)


if __name__ == "__main__":
    unittest.main()
