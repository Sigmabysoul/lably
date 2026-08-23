import unittest

import pymupdf

from services.crop import crop_flipkart_pdf


class CropValidationTest(unittest.TestCase):
    def test_rejects_negative_padding(self):
        with self.assertRaisesRegex(ValueError, "between 0 and 144"):
            crop_flipkart_pdf(b"%PDF-invalid", padding=-1)

    def test_rejects_excessive_padding(self):
        with self.assertRaisesRegex(ValueError, "between 0 and 144"):
            crop_flipkart_pdf(b"%PDF-invalid", padding=145)

    def test_skips_trailing_blank_page(self):
        source = pymupdf.open()
        label_page = source.new_page(width=400, height=500)
        label_page.insert_text((40, 40), "Handle with care")
        source.new_page(width=400, height=500)
        contents = source.tobytes()
        source.close()

        result = crop_flipkart_pdf(contents)
        output = pymupdf.open(stream=result.getvalue(), filetype="pdf")
        self.assertEqual(output.page_count, 1)
        output.close()


if __name__ == "__main__":
    unittest.main()
