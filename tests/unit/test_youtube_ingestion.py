from pathlib import Path

import pytest

from app.ai.interfaces.stt import Transcript, TranscriptSegment
from app.rag.youtube_ingestion import (
    DownloadedYouTubeAsset,
    YouTubeIngestionError,
    YouTubeTranscriptIngestor,
    chunk_transcript,
    slice_transcript,
    validate_youtube_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://youtube.com/watch?v=abcdefghi",
        "https://youtube.com.evil.test/watch?v=abcdefghi",
        "https://user:secret@youtube.com/watch?v=abcdefghi",
        "https://127.0.0.1/watch?v=abcdefghi",
    ],
)
def test_validate_youtube_url_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(YouTubeIngestionError):
        validate_youtube_url(url)


def test_validate_youtube_url_accepts_known_https_hosts() -> None:
    assert validate_youtube_url("https://youtu.be/abcdefghijk") == "https://youtu.be/abcdefghijk"


def test_chunk_transcript_preserves_timestamp_ranges() -> None:
    transcript = Transcript(
        segments=(
            TranscriptSegment(0, 3, "Primer concepto"),
            TranscriptSegment(3, 7, "Segundo concepto"),
            TranscriptSegment(8, 12, "Tercer concepto con una explicación más extensa"),
        ),
        language="es",
    )

    chunks = chunk_transcript(transcript, source_id="video-1", max_characters=200)

    assert len(chunks) == 1
    assert chunks[0].timestamp_start == 0
    assert chunks[0].timestamp_end == 12
    assert chunks[0].chunk_id.startswith("video-1:")


class FakeDownloader:
    async def download(self, url: str, target_directory: Path) -> DownloadedYouTubeAsset:
        return DownloadedYouTubeAsset(
            video_id="abcdefghijk",
            title="Clase de prueba",
            canonical_url="https://www.youtube.com/watch?v=abcdefghijk",
            channel="Canal docente",
            duration_seconds=10,
            audio_path=target_directory / "abcdefghijk.webm",
        )


class FakeSpeechToText:
    async def transcribe(self, audio_path: Path) -> Transcript:
        return Transcript(
            segments=(TranscriptSegment(1, 4, "Contenido verificable"),),
            language="es",
            duration_seconds=4,
        )


class MissingCaptions:
    async def fetch(self, url: str, **kwargs) -> Transcript:
        raise YouTubeIngestionError("no captions")


@pytest.mark.asyncio
async def test_ingestor_coordinates_download_transcription_and_chunking(tmp_path: Path) -> None:
    ingestor = YouTubeTranscriptIngestor(
        FakeDownloader(),  # type: ignore[arg-type]
        FakeSpeechToText(),  # type: ignore[arg-type]
        MissingCaptions(),  # type: ignore[arg-type]
    )

    result = await ingestor.ingest(
        "https://youtu.be/abcdefghijk",
        source_id="video-docente",
        target_directory=tmp_path,
    )

    assert result.asset.channel == "Canal docente"
    assert result.chunks[0].timestamp_start == 1
    assert result.chunks[0].timestamp_end == 4
    assert result.chunks[0].content == "Contenido verificable"


def test_slice_transcript_keeps_only_overlapping_segments() -> None:
    transcript = Transcript(
        segments=(
            TranscriptSegment(0, 5, "Antes"),
            TranscriptSegment(5, 10, "Dentro"),
            TranscriptSegment(10, 15, "Después"),
        ),
        duration_seconds=15,
    )

    sliced = slice_transcript(
        transcript,
        start_time_seconds=5,
        end_time_seconds=10,
    )

    assert [item.text for item in sliced.segments] == ["Dentro"]


def test_slice_transcript_clamps_segments_crossing_requested_boundaries() -> None:
    transcript = Transcript(
        segments=(TranscriptSegment(4, 11, "Segmento que cruza el recorte"),),
        duration_seconds=11,
    )

    sliced = slice_transcript(
        transcript,
        start_time_seconds=5,
        end_time_seconds=10,
    )

    assert sliced.segments[0].start == 5
    assert sliced.segments[0].end == 10
    assert sliced.duration_seconds == 10
