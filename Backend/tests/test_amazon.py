import io
import unittest

from pypdf import PdfReader
from reportlab.pdfgen import canvas

from Backend.services.amazon import extract_sku_and_qty_from_text, process_amazon_pdf


def make_pdf(page_count: int = 4) -> bytes:
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(400, 600))
    for index in range(page_count):
        pdf.drawString(40, 500, f"Page {index + 1}")
        if index % 2:
            pdf.drawString(40, 450, f"( SKU_{index} ) HSN Qty: {index + 1}")
        pdf.showPage()
    pdf.save()
    return output.getvalue()


class AmazonProcessorTest(unittest.TestCase):
    def test_extracts_sku_and_quantity(self):
        self.assertEqual(
            extract_sku_and_qty_from_text("( ITEM_42 ) HSN Quantity: 3"),
            ("ITEM_42", "3"),
        )

    def test_processes_only_requested_pair(self):
        result = process_amazon_pdf(make_pdf(), "labels.pdf", pair_index=1)
        reader = PdfReader(result)
        self.assertEqual(len(reader.pages), 2)
        self.assertIn("SKU_3", reader.pages[0].extract_text())

    def test_rejects_pair_outside_document(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            process_amazon_pdf(make_pdf(2), "labels.pdf", pair_index=2)


if __name__ == "__main__":
    unittest.main()
