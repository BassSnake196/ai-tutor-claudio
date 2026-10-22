from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class SpeechToTextError(RuntimeError):
    """A local transcription provider could not process the media asset."""


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    segments: tuple[TranscriptSegment, ...]
    language: str | None = None
    duration_seconds: float | None = None

    @property
    def text(self) -> str:
        return " ".join(segment.text.strip() for segment in self.segments if segment.text.strip())


class SpeechToText(ABC):
    @abstractmethod
    async def transcribe(self, audio_path: Path) -> Transcript:
        """Transcribe a local asset while preserving segment timestamps."""
