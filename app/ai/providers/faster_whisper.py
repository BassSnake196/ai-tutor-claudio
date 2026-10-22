"""Lazy, CPU-friendly faster-whisper adapter."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.ai.interfaces.stt import (
    SpeechToText,
    SpeechToTextError,
    Transcript,
    TranscriptSegment,
)


class FasterWhisperSpeechToText(SpeechToText):
    def __init__(
        self,
        *,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = None,
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language = language
        self._model: Any | None = None
        self._model_lock = asyncio.Lock()

    async def transcribe(self, audio_path: Path) -> Transcript:
        resolved = audio_path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        model = await self._get_model()
        try:
            return await asyncio.to_thread(self._transcribe_sync, model, resolved)
        except SpeechToTextError:
            raise
        except Exception as exc:
            raise SpeechToTextError("La transcripción local no pudo completarse.") from exc

    async def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise SpeechToTextError(
                    "faster-whisper no está instalado en el entorno de la API."
                ) from exc
            self._model = await asyncio.to_thread(
                WhisperModel,
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
            return self._model

    def _transcribe_sync(self, model: Any, audio_path: Path) -> Transcript:
        segments, info = model.transcribe(
            str(audio_path),
            language=self._language,
            beam_size=5,
            vad_filter=True,
        )
        parsed = tuple(
            TranscriptSegment(
                start=max(0.0, float(segment.start)),
                end=max(float(segment.start), float(segment.end)),
                text=str(segment.text).strip(),
            )
            for segment in segments
            if str(segment.text).strip()
        )
        if not parsed:
            raise SpeechToTextError("El audio no produjo segmentos de texto utilizables.")
        duration = getattr(info, "duration", None)
        return Transcript(
            segments=parsed,
            language=getattr(info, "language", self._language),
            duration_seconds=float(duration) if duration is not None else parsed[-1].end,
        )
