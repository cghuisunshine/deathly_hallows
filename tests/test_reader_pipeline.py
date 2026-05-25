import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from tools import reader_pipeline


class ReaderPipelineTests(unittest.TestCase):
    def test_extract_chapters_skips_contents_and_splits_real_chapters(self):
        source = """
        Contents
        ONE
        Dudley Demented . 1
        TWO
        A Peck of Owls . 20

        Harry Potter
        And the Order OF Phoenix

        CHAPTER ONE

        DUDLEY DEMENTED

        First paragraph of chapter one.

        CHAPTER ONE

        Repeated page header should stay inside the first chapter body.

        Second paragraph.

        CHAPTER TWO

        A PECK OF OWLS

        Another chapter starts here.
        """

        chapters = reader_pipeline.extract_chapters(source)

        self.assertEqual([chapter.number for chapter in chapters], [1, 2])
        self.assertEqual(chapters[0].title, "Dudley Demented")
        self.assertEqual(chapters[1].title, "A Peck of Owls")
        self.assertIn("First paragraph", chapters[0].body)
        self.assertNotIn("Contents", chapters[0].body)

    def test_normalize_paragraphs_repairs_wrapped_lines_and_drops_page_artifacts(self):
        body = """
        T      he hottest day of the summer so far was drawing to a close and
               a drowsy silence lay over the large, square houses of Privet
        Drive.
                                     \x91   1   \x91

            On the whole, Harry thought he was to be congratulated on his
        idea of hiding here.
        """

        paragraphs = reader_pipeline.normalize_paragraphs(body)

        self.assertEqual(len(paragraphs), 2)
        self.assertEqual(
            paragraphs[0],
            "The hottest day of the summer so far was drawing to a close and a drowsy silence lay over the large, square houses of Privet Drive.",
        )
        self.assertEqual(
            paragraphs[1],
            "On the whole, Harry thought he was to be congratulated on his idea of hiding here.",
        )

    def test_normalize_paragraphs_uses_indents_and_drops_running_headers(self):
        body = textwrap.dedent("""
        First paragraph continues
        across this wrapped line.
            Second paragraph starts by indentation.
        DUDLEY DEMENTED
        More text in the second paragraph.
        """)

        paragraphs = reader_pipeline.normalize_paragraphs(body, running_headers={"DUDLEY DEMENTED"})

        self.assertEqual(
            paragraphs,
            [
                "First paragraph continues across this wrapped line.",
                "Second paragraph starts by indentation. More text in the second paragraph.",
            ],
        )

    def test_normalize_paragraphs_drops_numbered_book_running_headers(self):
        body = """
        The effect was incredible: Dudley gasped and fell off his chair.
        8                         HARRY POTTER
        clapped her hands to her mouth.
        """

        paragraphs = reader_pipeline.normalize_paragraphs(body)

        self.assertEqual(
            paragraphs,
            ["The effect was incredible: Dudley gasped and fell off his chair. clapped her hands to her mouth."],
        )

    def test_normalize_paragraphs_preserves_compound_hyphen_line_breaks(self):
        body = """
        top-of-
        the-range broomstick

        sum-
        mer holidays
        """

        paragraphs = reader_pipeline.normalize_paragraphs(body)

        self.assertEqual(paragraphs, ["top-of-the-range broomstick", "summer holidays"])

    def test_extract_chapter_without_visible_title_keeps_body(self):
        source = """
        CHAPTER THREE

        But Hedwig didn't return next morning. Harry spent the day in his
        bedroom.
        """

        chapters = reader_pipeline.extract_chapters(source)

        self.assertEqual(chapters[0].number, 3)
        self.assertEqual(chapters[0].title, "The Advance Guard")
        self.assertTrue(chapters[0].body.startswith("But Hedwig"))

    def test_split_title_and_body_strips_mixed_case_printed_title(self):
        title, body = reader_pipeline.split_title_and_body("""
        The Ghoul in Pajamas

        First paragraph starts here.
        """)

        self.assertEqual(title, "The Ghoul in Pajamas")
        self.assertTrue(body.strip().startswith("First paragraph"))

    def test_extract_chapters_accepts_decorative_headings_and_expected_titles(self):
        source = """
        Front matter

                  — CHAPTER ONE —



              The Worst Birthday
        First paragraph starts here.

        THE WORST BIRTHDAY 9
        Wrapped line continues.

                  — CHAPTER TWO —

              Dobby's Warning
        Another chapter starts here.
        """

        chapters = reader_pipeline.extract_chapters(
            source,
            chapter_titles={1: "The Worst Birthday", 2: "Dobby's Warning"},
            chapter_count=2,
        )

        self.assertEqual([chapter.number for chapter in chapters], [1, 2])
        self.assertEqual(chapters[0].title, "The Worst Birthday")
        self.assertTrue(chapters[0].body.startswith("First paragraph"))
        self.assertNotIn("The Worst Birthday", chapters[0].body.splitlines()[0])

    def test_extract_chapters_accepts_numeric_headings_and_split_expected_titles(self):
        source = """
        Contents
        1 The Dark Lord Ascending         1
        2 In Memoriam                    13

        Chapter 1

        The Dark Lord
        Ascending

        First paragraph starts here.

                            Chapter 1

        Running page header should stay inside the chapter body.

        Chapter 2

        In Memoriam

        Another chapter starts here.
        """

        chapters = reader_pipeline.extract_chapters(
            source,
            chapter_titles={1: "The Dark Lord Ascending", 2: "In Memoriam"},
            chapter_count=2,
        )

        self.assertEqual([chapter.number for chapter in chapters], [1, 2])
        self.assertEqual(chapters[0].title, "The Dark Lord Ascending")
        self.assertTrue(chapters[0].body.startswith("First paragraph"))
        self.assertNotIn("The Dark Lord", chapters[0].body.splitlines()[0])

    def test_audio_chapter_spans_from_metadata_split_multi_chapter_parts(self):
        metadata = {
            "title": "Example Book",
            "spine": [{"duration": 100.0}, {"duration": 200.0}],
            "chapters": [
                {"title": "Chapter 1:  One", "spine": 0, "offset": 0},
                {"title": "Chapter 2:  Two", "spine": 0, "offset": 40},
                {"title": "Chapter 3:  Three", "spine": 1, "offset": 0},
                {"title": "Next Chapter:  Preview", "spine": 1, "offset": 180},
            ],
        }

        config = reader_pipeline.book_config_from_metadata(metadata)
        spans = reader_pipeline.audio_chapter_spans_from_metadata(metadata)

        self.assertEqual(config.title, "Example Book")
        self.assertEqual(config.chapter_titles, {1: "One", 2: "Two", 3: "Three"})
        self.assertEqual(len(spans), 3)
        self.assertEqual(spans[0].spine_index, 0)
        self.assertEqual(spans[0].start, 0.0)
        self.assertEqual(spans[0].end, 40.0)
        self.assertEqual(spans[1].start, 40.0)
        self.assertEqual(spans[1].end, 100.0)
        self.assertEqual(spans[2].spine_index, 1)
        self.assertEqual(spans[2].end, 180.0)

    def test_build_reader_manifest_offsets_chapter_fragments_and_appends_outro(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            align_dir = root / "alignments"
            align_dir.mkdir()
            (align_dir / "chapter_001.json").write_text(
                json.dumps(
                    {
                        "fragments": [
                            {"id": "f000001", "begin": "0.000", "end": "1.500", "lines": ["First"]},
                            {"id": "f000002", "begin": "1.500", "end": "3.000", "lines": ["Second"]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (align_dir / "chapter_002.json").write_text(
                json.dumps(
                    {
                        "fragments": [
                            {"id": "f000001", "begin": "0.000", "end": "2.000", "lines": ["Third"]},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            chapters = [
                reader_pipeline.Chapter(1, "One", "First\n\nSecond"),
                reader_pipeline.Chapter(2, "Two", "Third"),
            ]
            audio_files = [Path("Part 001.mp3"), Path("Part 002.mp3")]

            manifest = reader_pipeline.build_reader_manifest(
                chapters=chapters,
                audio_files=audio_files,
                alignment_dir=align_dir,
                durations=[3.0, 2.0],
                title="Example Book",
                outro_audio=Path("Part 039.mp3"),
                outro_duration=100.0,
            )

        self.assertEqual(manifest["title"], "Example Book")
        self.assertEqual(len(manifest["chapters"]), 3)
        self.assertEqual(manifest["chapters"][1]["start"], 3.0)
        self.assertEqual(manifest["chapters"][1]["paragraphs"][0]["begin"], 3.0)
        self.assertEqual(manifest["chapters"][2]["kind"], "outro")
        self.assertEqual(manifest["duration"], 105.0)

    def test_reader_html_persists_and_restores_latest_paragraph(self):
        manifest = {
            "title": "Example Book",
            "duration": 3.0,
            "chapters": [
                {
                    "kind": "chapter",
                    "number": 1,
                    "title": "One",
                    "audio": "chapter_001.mp3",
                    "start": 0.0,
                    "duration": 3.0,
                    "paragraphs": [
                        {
                            "id": "c001_f000001",
                            "text": "First",
                            "begin": 0.0,
                            "end": 1.5,
                            "localBegin": 0.0,
                            "localEnd": 1.5,
                        }
                    ],
                }
            ],
        }

        html = reader_pipeline.build_reader_html(manifest)

        self.assertIn('const progressKey = "alignedReaderProgress:Example Book";', html)
        self.assertIn("function saveProgress(paragraphId) {", html)
        self.assertIn("function loadSavedProgress() {", html)
        self.assertIn("const savedProgress = loadSavedProgress();", html)
        self.assertIn("loadChapter(savedProgress.index, false, savedProgress.paragraphId);", html)


if __name__ == "__main__":
    unittest.main()
