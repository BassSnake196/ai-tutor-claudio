"""Safe single-video download and timestamp-preserving transcript chunking."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.ai.interfaces.stt import SpeechToText, Transcript, TranscriptSegment


YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtube-nocookie.com",
}
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


class YouTubeIngestionError(ValueError):
    """The requested YouTube asset is unsafe, unsupported or unavailable."""


@dataclass(frozen=True)
class DownloadedYouTubeAsset:
    video_id: str
    title: str
    canonical_url: str
    channel: str | None
    duration_seconds: float | None
    audio_path: Path | None


@dataclass(frozen=True)
class TimedTextChunk:
    chunk_id: str
    content: str
    index: int
    timestamp_start: float
    timestamp_end: float


@dataclass(frozen=True)
class IngestedYouTubeTranscript:
    asset: DownloadedYouTubeAsset
    transcript: Transcript
    chunks: tuple[TimedTextChunk, ...]


def validate_youtube_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme.casefold() != "https" or parsed.hostname is None:
        raise YouTubeIngestionError("YouTube requiere una URL HTTPS válida.")
    host = parsed.hostname.casefold().rstrip(".")
    if host not in YOUTUBE_HOSTS or parsed.username or parsed.password:
        raise YouTubeIngestionError("La URL no pertenece a un dominio permitido de YouTube.")
    return parsed.geturl()


def youtube_video_id(url: str) -> str:
    safe_url = validate_youtube_url(url)
    parsed = urlsplit(safe_url)
    host = (parsed.hostname or "").casefold()
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/", 1)[0]
    elif parsed.path == "/watch":
        candidate = parse_qs(parsed.query).get("v", [""])[0]
    elif parsed.path.startswith(("/shorts/", "/embed/")):
        candidate = parsed.path.split("/", 2)[2].split("/", 1)[0]
    else:
        candidate = ""
    if not VIDEO_ID_PATTERN.fullmatch(candidate):
        raise YouTubeIngestionError("La URL no contiene un identificador de video válido.")
    return candidate


class YouTubeCaptionService:
    """Retrieve public captions without downloading media when YouTube provides them."""

    async def fetch(
        self,
        url: str,
        *,
        languages: tuple[str, ...] = ("es", "es-MX", "en"),
    ) -> Transcript:
        video_id = youtube_video_id(url)
        return await asyncio.to_thread(self._fetch_sync, video_id, languages)

    @staticmethod
    def _fetch_sync(video_id: str, languages: tuple[str, ...]) -> Transcript:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            fetched = YouTubeTranscriptApi().fetch(video_id, languages=languages)
        except Exception as exc:
            raise YouTubeIngestionError("YouTube no ofrece subtítulos accesibles para el video.") from exc
        segments = tuple(
            TranscriptSegment(
                start=max(0.0, float(item.start)),
                end=max(float(item.start), float(item.start) + float(item.duration)),
                text=str(item.text).strip(),
            )
            for item in fetched
            if str(item.text).strip()
        )
        if not segments:
            raise YouTubeIngestionError("Los subtítulos del video están vacíos.")
        return Transcript(
            segments=segments,
            language=getattr(fetched, "language_code", None),
            duration_seconds=segments[-1].end,
        )


def chunk_transcript(
    transcript: Transcript,
    *,
    source_id: str,
    max_characters: int = 1_200,
) -> tuple[TimedTextChunk, ...]:
    if max_characters < 200:
        raise ValueError("max_characters debe ser al menos 200.")
    chunks: list[TimedTextChunk] = []
    current: list[TranscriptSegment] = []
    current_size = 0

    def flush() -> None:
        nonlocal current, current_size
        if not current:
            return
        content = " ".join(item.text.strip() for item in current if item.text.strip()).strip()
        if content:
            index = len(chunks)
            digest = sha256(f"{source_id}:{index}:{content}".encode("utf-8")).hexdigest()[:16]
            chunks.append(
                TimedTextChunk(
                    chunk_id=f"{source_id}:{digest}",
                    content=content,
                    index=index,
                    timestamp_start=current[0].start,
                    timestamp_end=current[-1].end,
                )
            )
        current = []
        current_size = 0

    for segment in transcript.segments:
        text = " ".join(segment.text.split())
        if not text:
            continue
        if current and current_size + 1 + len(text) > max_characters:
            flush()
        current.append(TranscriptSegment(segment.start, segment.end, text))
        current_size += len(text) + (1 if current_size else 0)
    flush()
    return tuple(chunks)


def slice_transcript(
    transcript: Transcript,
    *,
    start_time_seconds: float | None = None,
    end_time_seconds: float | None = None,
) -> Transcript:
    if start_time_seconds is None and end_time_seconds is None:
        return transcript
    start = start_time_seconds or 0.0
    end = end_time_seconds if end_time_seconds is not None else float("inf")
    segments = tuple(
        TranscriptSegment(
            start=max(segment.start, start),
            end=min(segment.end, end),
            text=segment.text,
        )
        for segment in transcript.segments
        if segment.end > start and segment.start < end
    )
    if not segments:
        raise YouTubeIngestionError("El rango solicitado no contiene segmentos transcribibles.")
    return Transcript(
        segments=segments,
        language=transcript.language,
        duration_seconds=min(transcript.duration_seconds or segments[-1].end, end),
    )


class YouTubeDownloader:
    def __init__(
        self,
        *,
        maximum_duration_seconds: int = 7_200,
        maximum_file_bytes: int = 500 * 1024 * 1024,
        socket_timeout_seconds: int = 30,
    ) -> None:
        self._maximum_duration_seconds = maximum_duration_seconds
        self._maximum_file_bytes = maximum_file_bytes
        self._socket_timeout_seconds = socket_timeout_seconds

    async def download(self, url: str, target_directory: Path) -> DownloadedYouTubeAsset:
        safe_url = validate_youtube_url(url)
        target = target_directory.resolve()
        target.mkdir(parents=True, exist_ok=True)
        return await asyncio.to_thread(self._download_sync, safe_url, target)

    def _download_sync(self, url: str, target: Path) -> DownloadedYouTubeAsset:
        try:
            import yt_dlp
        except ImportError as exc:
            raise YouTubeIngestionError("yt-dlp no está instalado en el entorno de la API.") from exc

        def reject_oversized(info: dict[str, Any], *, incomplete: bool = False) -> str | None:
            duration = info.get("duration")
            if duration is not None and float(duration) > self._maximum_duration_seconds:
                return "El video supera la duración máxima permitida."
            return None

        options: dict[str, Any] = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "socket_timeout": self._socket_timeout_seconds,
            "max_filesize": self._maximum_file_bytes,
            "outtmpl": str(target / "%(id)s.%(ext)s"),
            "match_filter": reject_oversized,
        }
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=True)
                if info is None or info.get("_type") == "playlist":
                    raise YouTubeIngestionError("Sólo se permite descargar un video individual.")
                video_id = str(info.get("id") or "")
                if not VIDEO_ID_PATTERN.fullmatch(video_id):
                    raise YouTubeIngestionError("YouTube no devolvió un identificador de video válido.")
                prepared = Path(downloader.prepare_filename(info)).resolve()
        except YouTubeIngestionError:
            raise
        except Exception as exc:
            raise YouTubeIngestionError("No se pudo descargar el audio de YouTube.") from exc

        if not prepared.is_relative_to(target) or not prepared.is_file():
            raise YouTubeIngestionError("La descarga no produjo un archivo local seguro.")
        if prepared.stat().st_size > self._maximum_file_bytes:
            prepared.unlink(missing_ok=True)
            raise YouTubeIngestionError("El audio supera el tamaño máximo permitido.")

        duration = info.get("duration")
        return DownloadedYouTubeAsset(
            video_id=video_id,
            title=str(info.get("title") or video_id),
            canonical_url=f"https://www.youtube.com/watch?v={video_id}",
            channel=str(info["channel"]) if info.get("channel") else None,
            duration_seconds=float(duration) if duration is not None else None,
            audio_path=prepared,
        )


class YouTubeTranscriptIngestor:
    def __init__(
        self,
        downloader: YouTubeDownloader,
        speech_to_text: SpeechToText,
        captions: YouTubeCaptionService | None = None,
    ) -> None:
        self._downloader = downloader
        self._speech_to_text = speech_to_text
        self._captions = captions or YouTubeCaptionService()

    async def ingest(
        self,
        url: str,
        *,
        source_id: str,
        target_directory: Path,
        language: str = "es",
        start_time_seconds: float | None = None,
        end_time_seconds: float | None = None,
    ) -> IngestedYouTubeTranscript:
        try:
            transcript = await self._captions.fetch(
                url,
                languages=tuple(dict.fromkeys((language, language.split("-", 1)[0], "es", "en"))),
            )
        except YouTubeIngestionError:
            asset = await self._downloader.download(url, target_directory)
            assert asset.audio_path is not None
            transcript = await self._speech_to_text.transcribe(asset.audio_path)
        else:
            video_id = youtube_video_id(url)
            asset = DownloadedYouTubeAsset(
                video_id=video_id,
                title=video_id,
                canonical_url=f"https://www.youtube.com/watch?v={video_id}",
                channel=None,
                duration_seconds=transcript.duration_seconds,
                audio_path=None,
            )
        transcript = slice_transcript(
            transcript,
            start_time_seconds=start_time_seconds,
            end_time_seconds=end_time_seconds,
        )
        chunks = chunk_transcript(transcript, source_id=source_id)
        if not chunks:
            raise YouTubeIngestionError("La transcripción no contiene texto indexable.")
        return IngestedYouTubeTranscript(asset=asset, transcript=transcript, chunks=chunks)
