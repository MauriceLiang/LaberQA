import unittest
from itertools import pairwise

from app.services.text import TextChunker, TextCleaner


class TextCleanerTests(unittest.TestCase):
    def test_normalizes_whitespace_without_changing_text(self) -> None:
        source = "  第一条\t劳动者应当\r\n\r\n依法维权。  "

        cleaned = TextCleaner.clean(source)

        self.assertEqual(cleaned, "第一条 劳动者应当\n\n依法维权。")
        self.assertEqual("".join(source.split()), "".join(cleaned.split()))

    def test_empty_input_stays_empty(self) -> None:
        self.assertEqual(TextCleaner.clean(" \r\n\t "), "")


class TextChunkerTests(unittest.TestCase):
    def test_defaults_match_the_documented_chunk_size_and_overlap(self) -> None:
        chunker = TextChunker()

        self.assertEqual(chunker.chunk_size, 600)
        self.assertEqual(chunker.chunk_overlap, 100)

    def test_prefers_clause_boundary_over_paragraph_and_sentence(self) -> None:
        text = "第一条甲乙。\n普通段丙丁戊。第二条己庚辛壬。"

        chunks = TextChunker(chunk_size=25, chunk_overlap=0).chunk(text)

        self.assertEqual(chunks[0].content, "第一条甲乙。\n普通段丙丁戊。")
        self.assertTrue(chunks[1].content.startswith("第二条"))

    def test_prefers_sentence_boundary_over_fixed_length(self) -> None:
        chunks = TextChunker(chunk_size=8, chunk_overlap=0).chunk(
            "甲乙。丙丁戊己。庚辛壬"
        )

        self.assertEqual(chunks[0].content, "甲乙。丙丁戊己。")

    def test_fixed_length_chunks_overlap_and_are_numbered_from_one(self) -> None:
        text = "甲" * 50

        chunks = TextChunker(chunk_size=10, chunk_overlap=2).chunk(text)

        self.assertEqual([chunk.chunk_no for chunk in chunks], [1, 2, 3, 4, 5, 6])
        self.assertTrue(all(0 < len(chunk.content) <= 10 for chunk in chunks))
        for previous, current in pairwise(chunks):
            self.assertEqual(previous.content[-2:], current.content[:2])
        self.assertEqual("".join(chunk.content for chunk in chunks).count("甲"), 60)

    def test_empty_input_has_no_chunks(self) -> None:
        self.assertEqual(TextChunker().chunk(" \n\t"), [])

    def test_chunk_parameters_are_validated(self) -> None:
        for chunk_size, chunk_overlap in ((0, 0), (10, -1), (10, 10)):
            with (
                self.subTest(chunk_size=chunk_size, chunk_overlap=chunk_overlap),
                self.assertRaises(ValueError),
            ):
                TextChunker(chunk_size, chunk_overlap)


if __name__ == "__main__":
    unittest.main()
