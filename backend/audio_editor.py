"""
Audio Narration Pause Analyzer & Remover.

Pure-FFmpeg implementation - keine Python-Audio-Libraries noetig. ffmpeg
und ffprobe muessen im PATH liegen (auf der Windows-Maschine sollten
beide ueber https://ffmpeg.org bzw. das Standard-Installationsskript
verfuegbar sein).

Vier Public-Functions:
  get_audio_samples(audio_path, max_points)      -> Waveform-Daten
  detect_silences(audio_path, thresh_db, min_ms) -> Silence-Regions
  remove_silences(audio_path, output_path, ...)  -> bereinigtes MP3
  get_silence_stats(silences, total_duration)    -> Statistik-Block
"""
from __future__ import annotations

import asyncio
import logging
import re
import struct
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger("fusion-auto.audio-editor")


# ---------------------------------------------------------------------------
# Subprocess Helpers
# ---------------------------------------------------------------------------


class FFmpegMissingError(RuntimeError):
    """ffmpeg / ffprobe ist nicht im PATH installiert."""


def _run_sync(cmd: list[str]) -> tuple[bytes, bytes, int]:
    """Synchrones subprocess.run. Wirft FFmpegMissingError wenn Binary fehlt.

    Wir benutzen subprocess.run statt asyncio.create_subprocess_exec, weil
    letzteres auf Windows einen ProactorEventLoop voraussetzt - bei einem
    SelectorEventLoop wirft es NotImplementedError. subprocess.run im
    Threadpool ist plattformunabhaengig.
    """
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as exc:
        bin_name = cmd[0]
        raise FFmpegMissingError(
            f"'{bin_name}' nicht gefunden. ffmpeg + ffprobe muessen im PATH "
            f"installiert sein (siehe https://ffmpeg.org/download.html)."
        ) from exc
    return proc.stdout or b"", proc.stderr or b"", proc.returncode or 0


async def _run(cmd: list[str], capture_stderr: bool = False) -> tuple[bytes, bytes, int]:
    """Async-Facade: laeuft subprocess.run im Default-Threadpool, damit der
    FastAPI-Eventloop nicht blockiert."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run_sync, cmd)


# ---------------------------------------------------------------------------
# Duration via ffprobe
# ---------------------------------------------------------------------------


async def _probe_duration(audio_path: Path) -> float:
    """Gibt die Dauer der Audio-Datei in Sekunden zurueck."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    out, err, rc = await _run(cmd)
    if rc != 0:
        raise RuntimeError(f"ffprobe fehlgeschlagen: {err.decode('utf-8', 'ignore')[:300]}")
    text = out.decode("utf-8", "ignore").strip()
    try:
        return float(text)
    except ValueError as exc:
        raise RuntimeError(f"ffprobe lieferte ungueltige Dauer: {text!r}") from exc


# ---------------------------------------------------------------------------
# 1) get_audio_samples
# ---------------------------------------------------------------------------


async def get_audio_samples(audio_path: Path, max_points: int = 2000) -> dict[str, Any]:
    """Extrahiert Waveform-Daten fuer die SVG-Visualisierung.

    Holt ueber ffprobe die Dauer, dann ueber ffmpeg rohes mono PCM (s16le)
    bei einer Sample-Rate `max_points / duration` (gecapped bei 8000 Hz).
    Die 16-bit signed Integers werden auf 0..1 absolute normalisiert und
    auf max_points heruntergesampled (Max pro Chunk).

    Returns: {samples: [float], duration: float, sample_rate: int}
    """
    if max_points < 50:
        max_points = 50

    duration = await _probe_duration(audio_path)
    if duration <= 0:
        return {"samples": [], "duration": 0.0, "sample_rate": 0}

    target_sr = int(max_points / duration)
    target_sr = max(50, min(8000, target_sr))

    cmd = [
        "ffmpeg",
        "-v", "error",
        "-i", str(audio_path),
        "-ac", "1",                  # mono
        "-ar", str(target_sr),       # decimated sample rate
        "-f", "s16le",               # raw signed 16-bit little-endian
        "-",
    ]
    out, err, rc = await _run(cmd)
    if rc != 0:
        raise RuntimeError(f"ffmpeg PCM-Extract fehlgeschlagen: {err.decode('utf-8', 'ignore')[:300]}")

    n = len(out) // 2
    if n == 0:
        return {"samples": [], "duration": duration, "sample_rate": target_sr}

    # Unpack signed 16-bit -> Liste, normalisiert auf [0, 1]
    samples_raw = struct.unpack(f"<{n}h", out[: n * 2])
    inv = 1.0 / 32768.0
    abs_norm = [abs(s) * inv for s in samples_raw]

    # Auf max_points Buckets reduzieren (Max pro Bucket - das gibt eine
    # 'lautere' Waveform als Mittelwert).
    if n <= max_points:
        downsampled = abs_norm
    else:
        bucket = n / max_points
        downsampled = []
        for i in range(max_points):
            lo = int(i * bucket)
            hi = int((i + 1) * bucket)
            if hi <= lo:
                hi = lo + 1
            downsampled.append(max(abs_norm[lo:hi]))

    return {
        "samples": [round(v, 4) for v in downsampled],
        "duration": round(duration, 3),
        "sample_rate": target_sr,
    }


# ---------------------------------------------------------------------------
# 2) detect_silences
# ---------------------------------------------------------------------------


_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
_SILENCE_END_RE = re.compile(
    r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)\s*\|\s*silence_duration:\s*([0-9]+(?:\.[0-9]+)?)"
)


async def detect_silences(
    audio_path: Path,
    silence_thresh_db: float = -35.0,
    min_silence_ms: int = 300,
) -> list[dict[str, float]]:
    """Erkennt Silence-Regionen via ffmpeg silencedetect Filter.

    silence_thresh_db: alles unter diesem Pegel zaehlt als Silence (negativ).
    min_silence_ms: nur Regionen die laenger als das sind, werden gemeldet.

    Returns: Liste von {start, end, duration} (in Sekunden, 3 Nachkomma).
    """
    min_dur_s = max(0.001, min_silence_ms / 1000.0)
    cmd = [
        "ffmpeg",
        "-v", "info",                # damit silencedetect-Logs auf stderr landen
        "-i", str(audio_path),
        "-af", f"silencedetect=noise={silence_thresh_db}dB:d={min_dur_s:.3f}",
        "-f", "null",
        "-",
    ]
    _out, err, rc = await _run(cmd)
    if rc != 0:
        # silencedetect kann selbst bei rc != 0 brauchbares stderr liefern -
        # nur abbrechen wenn wirklich nichts kam.
        text = err.decode("utf-8", "ignore")
        if "silence_start" not in text and "silence_end" not in text:
            raise RuntimeError(f"ffmpeg silencedetect fehlgeschlagen: {text[:300]}")

    text = err.decode("utf-8", "ignore")
    starts = [float(m.group(1)) for m in _SILENCE_START_RE.finditer(text)]
    ends_durs = [(float(m.group(1)), float(m.group(2))) for m in _SILENCE_END_RE.finditer(text)]

    # Pairing: silence_start sollte mit silence_end matchen, in Reihenfolge.
    pairs: list[dict[str, float]] = []
    for i, start in enumerate(starts):
        if i >= len(ends_durs):
            break
        end, dur = ends_durs[i]
        pairs.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(dur, 3),
        })
    return pairs


# ---------------------------------------------------------------------------
# 3) remove_silences
# ---------------------------------------------------------------------------


async def remove_silences(
    audio_path: Path,
    output_path: Path,
    silences: list[dict[str, float]],
    offset_before: float = 0.0,
    offset_after: float = 0.0,
) -> Path:
    """Schneidet Silence-Regionen raus, behaelt aber konfigurierbares Padding.

    offset_before: Sekunden Atemraum die NACH einer Voice-Line / VOR dem Cut
                   beibehalten werden (>= 0).
    offset_after:  Sekunden die VOR der naechsten Voice-Line / NACH dem Cut
                   beibehalten werden (>= 0).

    Edge-Cases:
      - silences leer -> Datei wird zur output_path kopiert (re-encoded zu MP3).
      - alles Silence -> Datei kopiert (wir loeschen kein komplettes File).
      - Segments < 10ms werden uebersprungen.

    Output ist immer MP3 (libmp3lame, q=2).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = await _probe_duration(audio_path)
    offset_before = max(0.0, float(offset_before))
    offset_after = max(0.0, float(offset_after))

    sorted_sil = sorted(
        ({"start": float(s["start"]), "end": float(s["end"])} for s in silences),
        key=lambda x: x["start"],
    )

    # Gaps = Voice-Segmente (alles ZWISCHEN den Silences + Vor/Nach)
    voice_segments: list[tuple[float, float]] = []
    cursor = 0.0
    for sil in sorted_sil:
        seg_start = cursor
        seg_end = sil["start"] + offset_before  # padding nach Voice-Ende
        if seg_end > seg_start:
            voice_segments.append((seg_start, seg_end))
        cursor = max(cursor, sil["end"] - offset_after)  # padding vor naechster Voice
    # Tail nach letzter Silence
    if cursor < duration:
        voice_segments.append((cursor, duration))

    # Edge case: keine Silences -> einfach reencode-copy zu MP3
    if not voice_segments or sum(b - a for a, b in voice_segments) < 0.01:
        await _ffmpeg_reencode_to_mp3(audio_path, output_path)
        return output_path

    # Sehr kurze Segmente droppen
    voice_segments = [(a, b) for a, b in voice_segments if (b - a) >= 0.01]
    if not voice_segments:
        await _ffmpeg_reencode_to_mp3(audio_path, output_path)
        return output_path

    # Filter-Graph bauen: pro Segment ein atrim+asetpts, dann concat=all.
    parts = []
    for i, (a, b) in enumerate(voice_segments):
        parts.append(
            f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]"
        )
    concat_inputs = "".join(f"[a{i}]" for i in range(len(voice_segments)))
    filter_complex = (
        ";".join(parts)
        + f";{concat_inputs}concat=n={len(voice_segments)}:v=0:a=1[out]"
    )

    cmd = [
        "ffmpeg",
        "-v", "error",
        "-y",
        "-i", str(audio_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "libmp3lame",
        "-q:a", "2",
        str(output_path),
    ]
    _out, err, rc = await _run(cmd)
    if rc != 0:
        raise RuntimeError(f"ffmpeg silence-cut fehlgeschlagen: {err.decode('utf-8', 'ignore')[:500]}")
    return output_path


async def _ffmpeg_reencode_to_mp3(src: Path, dst: Path) -> None:
    cmd = [
        "ffmpeg",
        "-v", "error",
        "-y",
        "-i", str(src),
        "-c:a", "libmp3lame",
        "-q:a", "2",
        str(dst),
    ]
    _out, err, rc = await _run(cmd)
    if rc != 0:
        raise RuntimeError(f"ffmpeg reencode fehlgeschlagen: {err.decode('utf-8', 'ignore')[:300]}")


# ---------------------------------------------------------------------------
# 4) get_silence_stats
# ---------------------------------------------------------------------------


def get_silence_stats(silences: list[dict[str, float]], total_duration: float) -> dict[str, Any]:
    """Statistik-Block fuer das Stats-Display."""
    count = len(silences)
    total = sum(float(s.get("duration", 0.0)) for s in silences)
    pct = (total / total_duration * 100.0) if total_duration > 0 else 0.0
    avg = (total / count) if count else 0.0
    longest = max((float(s.get("duration", 0.0)) for s in silences), default=0.0)
    return {
        "count": count,
        "total_silence": round(total, 3),
        "percentage": round(pct, 2),
        "avg_duration": round(avg, 3),
        "longest": round(longest, 3),
    }
