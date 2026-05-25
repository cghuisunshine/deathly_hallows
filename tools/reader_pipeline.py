from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


BOOK_PDF = Path("Harry-Potter-and-the-Chamber-of-Secrets - Unknown.pdf")
AUDIO_DIR = Path("J. K. Rowling - Harry Potter and the Chamber of Secrets")
OUTPUT_DIR = Path("aligned_reader")
DEFAULT_BOOK_TITLE = "Harry Potter and the Order of the Phoenix"

CHAPTER_WORDS = [
    "ONE",
    "TWO",
    "THREE",
    "FOUR",
    "FIVE",
    "SIX",
    "SEVEN",
    "EIGHT",
    "NINE",
    "TEN",
    "ELEVEN",
    "TWELVE",
    "THIRTEEN",
    "FOURTEEN",
    "FIFTEEN",
    "SIXTEEN",
    "SEVENTEEN",
    "EIGHTEEN",
    "NINETEEN",
    "TWENTY",
    "TWENTY-ONE",
    "TWENTY-TWO",
    "TWENTY-THREE",
    "TWENTY-FOUR",
    "TWENTY-FIVE",
    "TWENTY-SIX",
    "TWENTY-SEVEN",
    "TWENTY-EIGHT",
    "TWENTY-NINE",
    "THIRTY",
    "THIRTY-ONE",
    "THIRTY-TWO",
    "THIRTY-THREE",
    "THIRTY-FOUR",
    "THIRTY-FIVE",
    "THIRTY-SIX",
    "THIRTY-SEVEN",
    "THIRTY-EIGHT",
]
WORD_TO_NUMBER = {word: index for index, word in enumerate(CHAPTER_WORDS, start=1)}
CHAPTER_TITLES = {
    1: "Dudley Demented",
    2: "A Peck of Owls",
    3: "The Advance Guard",
    4: "Number Twelve, Grimmauld Place",
    5: "The Order of the Phoenix",
    6: "The Noble and Most Ancient House of Black",
    7: "The Ministry of Magic",
    8: "The Hearing",
    9: "The Woes of Mrs. Weasley",
    10: "Luna Lovegood",
    11: "The Sorting Hat's New Song",
    12: "Professor Umbridge",
    13: "Detention with Dolores",
    14: "Percy and Padfoot",
    15: "The Hogwarts High Inquisitor",
    16: "In the Hog's Head",
    17: "Educational Decree Number Twenty-Four",
    18: "Dumbledore's Army",
    19: "The Lion and the Serpent",
    20: "Hagrid's Tale",
    21: "The Eye of the Snake",
    22: "St. Mungo's Hospital for Magical Maladies and Injuries",
    23: "Christmas on the Closed Ward",
    24: "Occlumency",
    25: "The Beetle at Bay",
    26: "Seen and Unforeseen",
    27: "The Centaur and the Sneak",
    28: "Snape's Worst Memory",
    29: "Career Advice",
    30: "Grawp",
    31: "O.W.L.s",
    32: "Out of the Fire",
    33: "Fight and Flight",
    34: "The Department of Mysteries",
    35: "Beyond the Veil",
    36: "The Only One He Ever Feared",
    37: "The Lost Prophecy",
    38: "The Second War Begins",
}


@dataclass(frozen=True)
class Chapter:
    number: int
    title: str
    body: str


@dataclass(frozen=True)
class BookConfig:
    title: str
    chapter_titles: dict[int, str]
    chapter_count: int


@dataclass(frozen=True)
class AudioChapterSpan:
    number: int
    title: str
    spine_index: int
    start: float
    end: float


DEFAULT_BOOK_CONFIG = BookConfig(
    title=DEFAULT_BOOK_TITLE,
    chapter_titles=CHAPTER_TITLES,
    chapter_count=len(CHAPTER_TITLES),
)


def clean_text(text: str) -> str:
    return (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\x0c", "\n\n")
        .replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2014", " - ")
        .replace("\u2013", "-")
        .replace("\x91", "")
        .replace("\x92", "")
        .replace("", "")
        .replace("", "")
    )


def normalize_chapter_word(raw: str) -> str:
    return re.sub(r"\s+", "-", raw.strip().replace("—", "-").replace("–", "-")).upper()


def parse_chapter_number(raw: str) -> int | None:
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    return WORD_TO_NUMBER.get(normalize_chapter_word(raw))


def display_chapter_word(number: int) -> str:
    return CHAPTER_WORDS[number - 1].replace("-", " ").title()


def title_case_heading(raw: str) -> str:
    words = " ".join(raw.split()).title().split()
    small_words = {"A", "An", "And", "At", "By", "For", "In", "Of", "On", "The", "To"}
    title = " ".join(
        word.lower() if index > 0 and word in small_words else word for index, word in enumerate(words)
    )
    title = title.replace("'S", "'s")
    title = title.replace("O.W.L.S", "O.W.L.s")
    title = title.replace("St. Mungo'S", "St. Mungo's")
    title = title.replace("Dumbledore'S", "Dumbledore's")
    title = title.replace("Snape'S", "Snape's")
    return title


def extract_chapters(
    raw_text: str,
    chapter_titles: dict[int, str] | None = None,
    chapter_count: int | None = None,
) -> list[Chapter]:
    titles = chapter_titles or CHAPTER_TITLES
    count = chapter_count or len(titles)
    text = clean_text(raw_text)
    heading_re = re.compile(r"(?im)^[^\w\n]*CHAPTER[ \t]+(\d+|[A-Za-z]+(?:[- \t]+[A-Za-z]+)?)[^\w\n]*$")
    matches = []
    expected_next = 1
    for match in heading_re.finditer(text):
        number = parse_chapter_number(match.group(1))
        if not matches and number is not None and number != expected_next:
            expected_next = number
        if number == expected_next:
            matches.append(match)
            expected_next += 1
        if expected_next > count:
            break

    chapters: list[Chapter] = []
    for index, match in enumerate(matches):
        number = parse_chapter_number(match.group(1))
        if number is None:
            continue
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[match.end() : next_start]
        title, body = split_title_and_body(section, expected_title=titles.get(number))
        chapters.append(Chapter(number=number, title=title or titles[number], body=body.strip()))

    return chapters


def looks_like_chapter_start(text: str, heading_end: int) -> bool:
    for line in text[heading_end:].splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        letters = [char for char in stripped if char.isalpha()]
        if not letters:
            return False
        uppercase = sum(1 for char in letters if char.isupper())
        return uppercase / len(letters) >= 0.7
    return False


def split_title_and_body(section: str, expected_title: str | None = None) -> tuple[str, str]:
    lines = section.splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1

    if expected_title:
        normalized_expected = normalize_title_for_match(expected_title)
        search_index = index
        while search_index < len(lines):
            line = lines[search_index].strip()
            matched_end = expected_title_match_end(lines, search_index, normalized_expected)
            if matched_end is not None:
                index = matched_end + 1
                while index < len(lines) and not lines[index].strip():
                    index += 1
                return expected_title, "\n".join(lines[index:])
            if line and not looks_like_title_line(line) and search_index > index + 8:
                break
            search_index += 1

    title_lines: list[str] = []
    while index < len(lines):
        line = lines[index].strip()
        if not title_lines and not looks_like_title_line(line):
            break
        if not line and title_lines:
            index += 1
            break
        if line:
            title_lines.append(line)
        index += 1

    return title_case_heading(" ".join(title_lines)), "\n".join(lines[index:])


def expected_title_match_end(lines: Sequence[str], start: int, normalized_expected: str) -> int | None:
    if not lines[start].strip():
        return None

    collected: list[str] = []
    for offset in range(0, 6):
        index = start + offset
        if index >= len(lines):
            return None
        line = lines[index].strip()
        if not line:
            return None
        collected.append(line)
        if normalize_title_for_match(" ".join(collected)) == normalized_expected:
            return index
    return None


def normalize_title_for_match(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", clean_text(value).upper())


def looks_like_title_line(line: str) -> bool:
    letters = [char for char in line if char.isalpha()]
    if not letters:
        return False
    uppercase = sum(1 for char in letters if char.isupper())
    if uppercase / len(letters) >= 0.7:
        return True
    return looks_like_title_case_line(line)


def looks_like_title_case_line(line: str) -> bool:
    line = clean_text(line).strip()
    if len(line) > 90 or line.endswith((".", "?", "!", ",", ";", ":")):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z.']*", line)
    if not words or len(words) > 12:
        return False
    small_words = {"a", "an", "and", "at", "by", "for", "in", "of", "on", "the", "to"}
    return all(word[0].isupper() or word.lower() in small_words for word in words)


def normalize_paragraphs(body: str, running_headers: Iterable[str] = ()) -> list[str]:
    header_set = {header.strip().upper() for header in running_headers}
    lines = []
    for raw_line in clean_text(body).splitlines():
        line = raw_line.strip()
        if is_page_artifact(line):
            continue
        if is_running_header(line, header_set):
            continue
        line = re.sub(r"\b([A-Z])\s{2,}([a-z])", r"\1\2", line)
        lines.append((raw_line, line))

    paragraphs: list[str] = []
    current: list[str] = []
    for raw_line, line in lines:
        if not line:
            flush_paragraph(current, paragraphs)
            current = []
            continue
        if current and is_indented_paragraph_start(raw_line):
            flush_paragraph(current, paragraphs)
            current = []
        current.append(line)
    flush_paragraph(current, paragraphs)
    return paragraphs


def is_running_header(line: str, header_set: set[str]) -> bool:
    upper = line.upper()
    if upper in header_set:
        return True
    for header in header_set:
        if re.fullmatch(rf"{re.escape(header)}\s+\d{{1,4}}", upper):
            return True
    return False


def is_page_artifact(line: str) -> bool:
    if not line:
        return False
    if re.fullmatch(r"\d{1,4}", line):
        return True
    if re.fullmatch(r"[·.\- ]*\d{1,4}[·.\- ]*", line):
        return True
    if re.fullmatch(r"\d{1,4}\s+[A-Z][A-Z .'\-]+", clean_text(line)):
        return True
    if re.fullmatch(r"CHAPTER\s+[A-Za-z]+(?:[- ]+[A-Za-z]+)?", line, flags=re.IGNORECASE):
        return True
    return False


def is_indented_paragraph_start(raw_line: str) -> bool:
    expanded = raw_line.expandtabs(4)
    stripped = expanded.lstrip()
    indent = len(expanded) - len(stripped)
    return 2 <= indent <= 5 and bool(stripped)


def flush_paragraph(lines: list[str], paragraphs: list[str]) -> None:
    if not lines:
        return
    paragraph = lines[0]
    for line in lines[1:]:
        if paragraph.endswith("-") and line[:1].islower():
            trailing_word = paragraph.rsplit(" ", 1)[-1]
            if trailing_word.count("-") > 1:
                paragraph += line
            else:
                paragraph = paragraph[:-1] + line
        else:
            paragraph += " " + line
    paragraph = re.sub(r"\s+", " ", paragraph).strip()
    if paragraph:
        paragraphs.append(paragraph)


def chapter_fragments(chapter: Chapter) -> list[str]:
    heading = f"Chapter {display_chapter_word(chapter.number)}. {chapter.title}."
    return [heading, *normalize_paragraphs(chapter.body, running_headers=running_headers_for(chapter))]


def running_headers_for(chapter: Chapter) -> set[str]:
    headers = {chapter.title.upper()}
    headers.update(title.upper() for title in CHAPTER_TITLES.values())
    headers.add("THE ADVANCED GUARD")
    return headers


def write_chapter_text_files(chapters: Sequence[Chapter], text_dir: Path) -> list[Path]:
    text_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for chapter in chapters:
        fragments = chapter_fragments(chapter)
        path = text_dir / f"chapter_{chapter.number:03d}.txt"
        path.write_text("\n".join(fragments) + "\n", encoding="utf-8")
        written.append(path)
    return written


def extract_pdf_text(pdf_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pdftotext", "-layout", str(pdf_path), str(output_path)], check=True)


def audio_parts(audio_dir: Path) -> list[Path]:
    return sorted(audio_dir.glob("Part *.mp3"))


def ffprobe_duration(audio_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return float(result.stdout.strip())


def prepare_inputs(pdf_path: Path, audio_dir: Path, output_dir: Path, book_config: BookConfig) -> list[Chapter]:
    raw_text_path = output_dir / "book.txt"
    extract_pdf_text(pdf_path, raw_text_path)
    chapters = extract_chapters(
        raw_text_path.read_text(encoding="utf-8"),
        chapter_titles=book_config.chapter_titles,
        chapter_count=book_config.chapter_count,
    )
    validate_chapters(chapters, book_config.chapter_count)
    parts = audio_parts(audio_dir)
    if not parts:
        raise RuntimeError(f"No audio parts found in {audio_dir}")
    write_chapter_text_files(chapters, output_dir / "text")
    return chapters


def validate_chapters(chapters: Sequence[Chapter], chapter_count: int = len(CHAPTER_TITLES)) -> None:
    numbers = [chapter.number for chapter in chapters]
    expected = list(range(1, chapter_count + 1))
    if numbers != expected:
        raise RuntimeError(f"Expected chapters 1-{chapter_count} in order, found {numbers}")
    small = [chapter.number for chapter in chapters if len(normalize_paragraphs(chapter.body)) < 5]
    if small:
        raise RuntimeError(f"Suspiciously small chapter extraction: {small}")


def run_aeneas(audio_path: Path, text_path: Path, output_path: Path, force: bool = False) -> None:
    if output_path.exists() and not force:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    config = "task_language=eng|is_text_type=plain|os_task_file_format=json"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "UTF-8"
    subprocess.run(
        [
            "conda",
            "run",
            "-n",
            "aeneas39",
            "python",
            "-m",
            "aeneas.tools.execute_task",
            str(audio_path),
            str(text_path),
            config,
            str(output_path),
        ],
        check=True,
        env=env,
    )


def align_all(
    audio_dir: Path,
    output_dir: Path,
    book_config: BookConfig,
    metadata: dict | None = None,
    force: bool = False,
) -> None:
    align_dir = output_dir / "alignments"
    text_dir = output_dir / "text"
    parts = chapter_audio_parts(audio_dir, output_dir, book_config, metadata, force=force)
    if len(parts) != book_config.chapter_count:
        raise RuntimeError(f"Expected {book_config.chapter_count} chapter audio parts, found {len(parts)}")
    for index, audio_path in enumerate(parts, start=1):
        text_path = text_dir / f"chapter_{index:03d}.txt"
        output_path = align_dir / f"chapter_{index:03d}.json"
        print(f"aligning chapter {index:03d}: {audio_path.name}", flush=True)
        run_aeneas(audio_path, text_path, output_path, force=force)
        validate_alignment_file(output_path, ffprobe_duration(audio_path))


def chapter_audio_parts(
    audio_dir: Path,
    output_dir: Path,
    book_config: BookConfig,
    metadata: dict | None = None,
    force: bool = False,
) -> list[Path]:
    if metadata:
        return split_audio_by_metadata(audio_dir, output_dir / "audio", metadata, force=force)
    parts = audio_parts(audio_dir)[: book_config.chapter_count]
    if len(parts) != book_config.chapter_count:
        raise RuntimeError(f"Expected {book_config.chapter_count} chapter audio parts, found {len(parts)}")
    return parts


def split_audio_by_metadata(audio_dir: Path, output_audio_dir: Path, metadata: dict, force: bool = False) -> list[Path]:
    parts = audio_parts(audio_dir)
    spans = audio_chapter_spans_from_metadata(metadata)
    output_audio_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for span in spans:
        if span.spine_index >= len(parts):
            raise RuntimeError(f"Metadata references missing audio spine {span.spine_index}")
        duration = span.end - span.start
        if duration <= 0:
            raise RuntimeError(f"Invalid duration for chapter {span.number}: {duration}")
        output_path = output_audio_dir / f"chapter_{span.number:03d}.mp3"
        if force or not output_path.exists():
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-ss",
                    f"{span.start:.3f}",
                    "-t",
                    f"{duration:.3f}",
                    "-i",
                    str(parts[span.spine_index]),
                    "-vn",
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "64k",
                    str(output_path),
                ],
                check=True,
            )
        outputs.append(output_path)
    return outputs


def load_metadata(path: Path | None) -> dict | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def book_config_from_metadata(metadata: dict) -> BookConfig:
    chapter_titles = {}
    for entry in metadata.get("chapters", []):
        parsed = parse_metadata_chapter_title(str(entry.get("title", "")))
        if parsed is None:
            continue
        number, title = parsed
        chapter_titles[number] = title
    if not chapter_titles:
        raise RuntimeError("No numbered chapters found in metadata")
    return BookConfig(
        title=str(metadata.get("title") or DEFAULT_BOOK_TITLE),
        chapter_titles=dict(sorted(chapter_titles.items())),
        chapter_count=max(chapter_titles),
    )


def parse_metadata_chapter_title(title: str) -> tuple[int, str] | None:
    match = re.match(r"\s*Chapter\s+(\d+)\s*:\s*(.+?)\s*$", title)
    if not match:
        return None
    return int(match.group(1)), match.group(2).strip()


def audio_chapter_spans_from_metadata(metadata: dict) -> list[AudioChapterSpan]:
    spine_durations = [float(item["duration"]) for item in metadata.get("spine", [])]
    raw_entries = metadata.get("chapters", [])
    spans = []
    real_chapters = []
    for entry in raw_entries:
        parsed = parse_metadata_chapter_title(str(entry.get("title", "")))
        if parsed is None:
            continue
        number, title = parsed
        real_chapters.append(
            {
                "number": number,
                "title": title,
                "spine": int(entry["spine"]),
                "offset": float(entry["offset"]),
            }
        )

    for index, chapter in enumerate(real_chapters):
        spine_index = chapter["spine"]
        end = spine_durations[spine_index]
        for later in raw_entries:
            if int(later.get("spine", -1)) != spine_index:
                continue
            later_offset = float(later.get("offset", 0))
            if later_offset > chapter["offset"]:
                end = later_offset
                break
        spans.append(
            AudioChapterSpan(
                number=chapter["number"],
                title=chapter["title"],
                spine_index=spine_index,
                start=chapter["offset"],
                end=end,
            )
        )
    return spans


def validate_alignment_file(path: Path, duration: float) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    last_end = 0.0
    for fragment in data.get("fragments", []):
        begin = float(fragment["begin"])
        end = float(fragment["end"])
        if begin < last_end - 0.001 or end < begin:
            raise RuntimeError(f"Non-monotonic timestamps in {path}")
        last_end = end
    if last_end <= 0:
        raise RuntimeError(f"No usable timestamps in {path}")
    if last_end > duration + 5:
        raise RuntimeError(f"Alignment exceeds audio duration in {path}: {last_end} > {duration}")


def build_reader_manifest(
    chapters: Sequence[Chapter],
    audio_files: Sequence[Path],
    alignment_dir: Path,
    durations: Sequence[float],
    title: str = DEFAULT_BOOK_TITLE,
    outro_audio: Path | None = None,
    outro_duration: float | None = None,
) -> dict:
    manifest = {"title": title, "duration": 0.0, "chapters": []}
    offset = 0.0
    for chapter, audio_path, duration in zip(chapters, audio_files, durations, strict=True):
        alignment_path = alignment_dir / f"chapter_{chapter.number:03d}.json"
        data = json.loads(alignment_path.read_text(encoding="utf-8"))
        paragraphs = []
        for fragment in data.get("fragments", []):
            begin = float(fragment["begin"])
            end = float(fragment["end"])
            text = " ".join(fragment.get("lines", [])).strip()
            paragraphs.append(
                {
                    "id": f"c{chapter.number:03d}_{fragment.get('id', len(paragraphs))}",
                    "text": text,
                    "begin": round(offset + begin, 3),
                    "end": round(offset + end, 3),
                    "localBegin": round(begin, 3),
                    "localEnd": round(end, 3),
                }
            )
        manifest["chapters"].append(
            {
                "kind": "chapter",
                "number": chapter.number,
                "title": chapter.title,
                "audio": audio_path.as_posix(),
                "start": round(offset, 3),
                "end": round(offset + duration, 3),
                "duration": round(duration, 3),
                "paragraphs": paragraphs,
            }
        )
        offset += duration

    if outro_audio is not None and outro_duration is not None:
        manifest["chapters"].append(
            {
                "kind": "outro",
                "number": None,
                "title": "Outro",
                "audio": outro_audio.as_posix(),
                "start": round(offset, 3),
                "end": round(offset + outro_duration, 3),
                "duration": round(outro_duration, 3),
                "paragraphs": [],
            }
        )
        offset += outro_duration

    manifest["duration"] = round(offset, 3)
    return manifest


def build_reader(output_dir: Path, audio_dir: Path, book_config: BookConfig, metadata: dict | None = None) -> None:
    raw_text = (output_dir / "book.txt").read_text(encoding="utf-8")
    chapters = extract_chapters(
        raw_text,
        chapter_titles=book_config.chapter_titles,
        chapter_count=book_config.chapter_count,
    )
    validate_chapters(chapters, book_config.chapter_count)
    if metadata:
        parts = sorted((output_dir / "audio").glob("chapter_*.mp3"))[: book_config.chapter_count]
        outro_audio = None
        outro_duration = None
    else:
        parts = audio_parts(audio_dir)
        outro_audio = relative_to_output(parts[book_config.chapter_count], output_dir) if len(parts) > book_config.chapter_count else None
        outro_duration = ffprobe_duration(parts[book_config.chapter_count]) if len(parts) > book_config.chapter_count else None
    if len(parts) != book_config.chapter_count:
        raise RuntimeError(f"Expected {book_config.chapter_count} chapter audio parts, found {len(parts)}")
    chapter_audio = [relative_to_output(path, output_dir) for path in parts]
    durations = [ffprobe_duration(path) for path in parts]
    manifest = build_reader_manifest(
        chapters=chapters,
        audio_files=chapter_audio,
        alignment_dir=output_dir / "alignments",
        durations=durations,
        title=book_config.title,
        outro_audio=outro_audio,
        outro_duration=outro_duration,
    )
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output_dir / "index.html").write_text(build_reader_html(manifest), encoding="utf-8")


def relative_to_output(path: Path, output_dir: Path) -> Path:
    return Path(os.path.relpath(path.resolve(), output_dir.resolve()))


def build_reader_html(manifest: dict) -> str:
    manifest_json = json.dumps(manifest, ensure_ascii=False)
    progress_key_json = json.dumps(f"alignedReaderProgress:{manifest['title']}")
    title = html.escape(manifest["title"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f5f4;
      --surface: #ffffff;
      --line: #d7d3cc;
      --text: #1c1917;
      --muted: #6b6258;
      --active: #fff3c4;
      --active-line: #b45309;
      --button: #1c1917;
      --button-text: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
      font-size: 16px;
      line-height: 1.55;
    }}
    .app {{
      min-height: 100vh;
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
    }}
    aside {{
      border-right: 1px solid var(--line);
      background: var(--surface);
      height: 100vh;
      position: sticky;
      top: 0;
      overflow: auto;
      padding: 20px 16px;
    }}
    .book-title {{
      font-size: 15px;
      font-weight: 700;
      margin: 0 0 16px;
      line-height: 1.3;
    }}
    .chapter-list {{
      display: flex;
      flex-direction: column;
      gap: 2px;
    }}
    .chapter-link {{
      width: 100%;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--text);
      cursor: pointer;
      display: grid;
      grid-template-columns: 32px 1fr;
      gap: 8px;
      padding: 8px;
      text-align: left;
      font: inherit;
      line-height: 1.3;
    }}
    .chapter-link:hover {{ background: #f0eee9; }}
    .chapter-link.active {{
      background: #e7e1d8;
      font-weight: 650;
    }}
    .chapter-number {{ color: var(--muted); font-variant-numeric: tabular-nums; }}
    main {{
      min-width: 0;
      padding: 28px 32px 112px;
    }}
    .topbar {{
      max-width: 840px;
      margin: 0 auto 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    h1 {{
      font-size: 22px;
      line-height: 1.25;
      margin: 0;
      font-weight: 750;
    }}
    .time {{
      color: var(--muted);
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }}
    .reader {{
      max-width: 840px;
      margin: 0 auto;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 28px 34px;
    }}
    .chapter-heading {{
      font-size: 20px;
      margin: 0 0 22px;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--line);
    }}
    .paragraph {{
      margin: 0 0 14px;
      padding: 3px 6px;
      border-left: 3px solid transparent;
      border-radius: 4px;
      cursor: pointer;
    }}
    .paragraph:hover {{ background: #f8f6f1; }}
    .paragraph.active {{
      background: var(--active);
      border-left-color: var(--active-line);
    }}
    .outro {{
      color: var(--muted);
      margin: 0;
    }}
    .player {{
      position: fixed;
      left: 280px;
      right: 0;
      bottom: 0;
      border-top: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.96);
      display: grid;
      grid-template-columns: auto auto auto minmax(120px, 1fr) auto;
      gap: 10px;
      align-items: center;
      padding: 12px 20px;
    }}
    button.control {{
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      color: var(--text);
      cursor: pointer;
      min-height: 36px;
      padding: 0 12px;
      font: inherit;
      font-weight: 650;
    }}
    button.primary {{
      background: var(--button);
      color: var(--button-text);
      border-color: var(--button);
      min-width: 68px;
    }}
    input[type="range"] {{
      width: 100%;
      accent-color: #b45309;
    }}
    @media (max-width: 760px) {{
      .app {{ display: block; }}
      aside {{
        position: static;
        height: auto;
        max-height: 240px;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }}
      main {{ padding: 20px 16px 120px; }}
      .reader {{ padding: 22px 18px; }}
      .topbar {{ align-items: flex-start; flex-direction: column; }}
      .player {{
        left: 0;
        grid-template-columns: auto auto auto;
      }}
      .player input[type="range"] {{
        grid-column: 1 / -1;
      }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <p class="book-title">{title}</p>
      <nav class="chapter-list" id="chapterList"></nav>
    </aside>
    <main>
      <div class="topbar">
        <h1 id="chapterTitle"></h1>
        <div class="time" id="timeLabel">0:00 / 0:00</div>
      </div>
      <article class="reader" id="reader"></article>
    </main>
  </div>
  <div class="player">
    <button class="control" id="prevButton" type="button">Prev</button>
    <button class="control primary" id="playButton" type="button">Play</button>
    <button class="control" id="nextButton" type="button">Next</button>
    <input id="seekBar" type="range" min="0" max="1000" value="0" aria-label="Seek">
    <span class="time" id="chapterTime">0:00</span>
  </div>
  <audio id="audio" preload="metadata"></audio>
  <script>
    const manifest = {manifest_json};
    const audio = document.getElementById('audio');
    const chapterList = document.getElementById('chapterList');
    const reader = document.getElementById('reader');
    const chapterTitle = document.getElementById('chapterTitle');
    const playButton = document.getElementById('playButton');
    const prevButton = document.getElementById('prevButton');
    const nextButton = document.getElementById('nextButton');
    const seekBar = document.getElementById('seekBar');
    const timeLabel = document.getElementById('timeLabel');
    const chapterTime = document.getElementById('chapterTime');
    const progressKey = {progress_key_json};
    let currentIndex = 0;
    let currentParagraphId = null;

    function formatTime(seconds) {{
      seconds = Math.max(0, Math.floor(seconds || 0));
      const h = Math.floor(seconds / 3600);
      const m = Math.floor((seconds % 3600) / 60);
      const s = seconds % 60;
      return h ? `${{h}}:${{String(m).padStart(2, '0')}}:${{String(s).padStart(2, '0')}}` : `${{m}}:${{String(s).padStart(2, '0')}}`;
    }}

    function findParagraphPosition(paragraphId) {{
      for (let index = 0; index < manifest.chapters.length; index += 1) {{
        const paragraph = manifest.chapters[index].paragraphs.find((item) => item.id === paragraphId);
        if (paragraph) {{
          return {{ index, paragraph }};
        }}
      }}
      return null;
    }}

    function saveProgress(paragraphId) {{
      const position = findParagraphPosition(paragraphId);
      if (!position) return;
      try {{
        localStorage.setItem(progressKey, JSON.stringify({{
          index: position.index,
          paragraphId,
          localBegin: position.paragraph.localBegin
        }}));
      }} catch (error) {{
        // localStorage can be unavailable in private or restricted browser contexts.
      }}
    }}

    function loadSavedProgress() {{
      try {{
        const raw = localStorage.getItem(progressKey);
        if (!raw) return null;
        const progress = JSON.parse(raw);
        const position = findParagraphPosition(progress.paragraphId);
        if (!position) return null;
        return {{
          index: position.index,
          paragraphId: position.paragraph.id,
          localBegin: position.paragraph.localBegin
        }};
      }} catch (error) {{
        return null;
      }}
    }}

    function renderNav() {{
      chapterList.innerHTML = '';
      manifest.chapters.forEach((chapter, index) => {{
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'chapter-link' + (index === currentIndex ? ' active' : '');
        const number = chapter.kind === 'chapter' ? String(chapter.number).padStart(2, '0') : '--';
        button.innerHTML = `<span class="chapter-number">${{number}}</span><span>${{chapter.title}}</span>`;
        button.addEventListener('click', () => loadChapter(index, true));
        chapterList.appendChild(button);
      }});
    }}

    function loadChapter(index, autoplay = false, startParagraphId = null) {{
      currentIndex = Math.max(0, Math.min(index, manifest.chapters.length - 1));
      const chapter = manifest.chapters[currentIndex];
      currentParagraphId = null;
      audio.src = chapter.audio;
      chapterTitle.textContent = chapter.kind === 'chapter' ? `Chapter ${{chapter.number}}. ${{chapter.title}}` : chapter.title;
      reader.innerHTML = '';
      if (chapter.paragraphs.length) {{
        chapter.paragraphs.forEach((paragraph) => {{
          const node = document.createElement('p');
          node.className = 'paragraph';
          node.id = paragraph.id;
          node.textContent = paragraph.text;
          node.addEventListener('click', () => {{
            audio.currentTime = paragraph.localBegin;
            audio.play();
          }});
          reader.appendChild(node);
        }});
      }} else {{
        const node = document.createElement('p');
        node.className = 'outro';
        node.textContent = 'Audio outro';
        reader.appendChild(node);
      }}
      renderNav();
      if (startParagraphId) {{
        const paragraph = chapter.paragraphs.find((item) => item.id === startParagraphId);
        if (paragraph) {{
          audio.currentTime = paragraph.localBegin;
        }}
      }}
      updateTimes();
      if (autoplay) {{
        audio.play();
      }}
    }}

    function updateTimes() {{
      const chapter = manifest.chapters[currentIndex];
      const local = audio.currentTime || 0;
      timeLabel.textContent = `${{formatTime(chapter.start + local)}} / ${{formatTime(manifest.duration)}}`;
      chapterTime.textContent = `${{formatTime(local)}} / ${{formatTime(chapter.duration)}}`;
      seekBar.value = chapter.duration ? String(Math.round((local / chapter.duration) * 1000)) : '0';
      updateHighlight(local);
    }}

    function updateHighlight(local) {{
      const chapter = manifest.chapters[currentIndex];
      const paragraph = chapter.paragraphs.find((item) => local >= item.localBegin && local < item.localEnd);
      const nextId = paragraph ? paragraph.id : null;
      if (nextId === currentParagraphId) return;
      if (currentParagraphId) {{
        document.getElementById(currentParagraphId)?.classList.remove('active');
      }}
      currentParagraphId = nextId;
      if (currentParagraphId) {{
        const node = document.getElementById(currentParagraphId);
        node?.classList.add('active');
        node?.scrollIntoView({{ block: 'center', behavior: 'smooth' }});
        saveProgress(currentParagraphId);
      }}
    }}

    playButton.addEventListener('click', () => {{
      if (audio.paused) {{
        audio.play();
      }} else {{
        audio.pause();
      }}
    }});
    prevButton.addEventListener('click', () => loadChapter(currentIndex - 1, !audio.paused));
    nextButton.addEventListener('click', () => loadChapter(currentIndex + 1, !audio.paused));
    seekBar.addEventListener('input', () => {{
      const chapter = manifest.chapters[currentIndex];
      audio.currentTime = (Number(seekBar.value) / 1000) * chapter.duration;
    }});
    audio.addEventListener('play', () => playButton.textContent = 'Pause');
    audio.addEventListener('pause', () => playButton.textContent = 'Play');
    audio.addEventListener('timeupdate', updateTimes);
    audio.addEventListener('loadedmetadata', updateTimes);
    audio.addEventListener('ended', () => {{
      if (currentIndex < manifest.chapters.length - 1) {{
        loadChapter(currentIndex + 1, true);
      }}
    }});

    const savedProgress = loadSavedProgress();
    if (savedProgress) {{
      loadChapter(savedProgress.index, false, savedProgress.paragraphId);
    }} else {{
      loadChapter(0, false);
    }}
  </script>
</body>
</html>
"""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a local synchronized audiobook reader.")
    parser.add_argument("command", choices=["prepare", "align", "build", "all"])
    parser.add_argument("--pdf", type=Path, default=BOOK_PDF)
    parser.add_argument("--audio-dir", type=Path, default=AUDIO_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--metadata", type=Path, default=None, help="audiobook metadata JSON; defaults to audio-dir/metadata/metadata.json when present")
    parser.add_argument("--title", default=None, help="override the reader title")
    parser.add_argument("--force", action="store_true", help="rerun existing Aeneas alignment files")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    metadata_path = args.metadata
    if metadata_path is None:
        candidate = args.audio_dir / "metadata" / "metadata.json"
        metadata_path = candidate if candidate.exists() else None
    metadata = load_metadata(metadata_path)
    book_config = book_config_from_metadata(metadata) if metadata else DEFAULT_BOOK_CONFIG
    if args.title:
        book_config = BookConfig(
            title=args.title,
            chapter_titles=book_config.chapter_titles,
            chapter_count=book_config.chapter_count,
        )
    if args.command in {"prepare", "all"}:
        prepare_inputs(args.pdf, args.audio_dir, args.output_dir, book_config)
    if args.command in {"align", "all"}:
        align_all(args.audio_dir, args.output_dir, book_config, metadata=metadata, force=args.force)
    if args.command in {"build", "all"}:
        build_reader(args.output_dir, args.audio_dir, book_config, metadata=metadata)
    if args.command in {"build", "all"}:
        print(f"reader ready: {args.output_dir / 'index.html'}")
    else:
        print(f"{args.command} complete: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
