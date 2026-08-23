import inspect
import unittest

from Backend.services.flipkart import process_flipkart_pdf


class FlipkartProcessorSignatureTest(unittest.TestCase):
    def test_accepts_from_address_kwarg(self):
        params = inspect.signature(process_flipkart_pdf).parameters
        self.assertIn("from_address", params)
        self.assertIsNone(params["from_address"].default)


if __name__ == "__main__":
    unittest.main()
