import unittest

from app.services.text import TextCleaner


class TextCleanerTests(unittest.TestCase):
    def test_normalizes_whitespace_without_changing_text(self) -> None:
        source = "  第一条\t劳动者应当\r\n\r\n依法维权。  "

        cleaned = TextCleaner.clean(source)

        self.assertEqual(cleaned, "第一条 劳动者应当\n\n依法维权。")
        self.assertEqual("".join(source.split()), "".join(cleaned.split()))

    def test_empty_input_stays_empty(self) -> None:
        self.assertEqual(TextCleaner.clean(" \r\n\t "), "")


if __name__ == "__main__":
    unittest.main()
