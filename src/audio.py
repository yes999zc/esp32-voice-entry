"""Audio primitives: Opus framing, resampling, VAD, ASR, segment capture."""
import datetime
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import opuslib
import sherpa_onnx

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


class OpusCodec:
    """16 kHz mono, fixed 60 ms frames (960 samples)."""

    def __init__(self, sample_rate: int, frame_ms: int, channels: int = 1):
        self.rate = sample_rate
        self.channels = channels
        self.frame_samples = int(sample_rate * frame_ms / 1000)
        self._enc = opuslib.Encoder(sample_rate, channels, opuslib.APPLICATION_VOIP)
        self._dec = opuslib.Decoder(sample_rate, channels)
        # Setting .bitrate raises "invalid argument" on this opuslib build;
        # the default VoIP bitrate is fine for 16 kHz speech.

    def decode(self, frame: bytes) -> np.ndarray:
        pcm = self._dec.decode(frame, self.frame_samples)
        return np.frombuffer(pcm, dtype=np.int16)

    def encode(self, pcm: np.ndarray) -> bytes:
        if len(pcm) != self.frame_samples:
            raise ValueError(f"need {self.frame_samples} samples, got {len(pcm)}")
        return self._enc.encode(pcm.astype(np.int16).tobytes(), self.frame_samples)

    def frames(self, pcm: np.ndarray):
        """Split a PCM buffer into encoded frames, padding the tail with silence."""
        n = self.frame_samples
        for off in range(0, len(pcm), n):
            chunk = pcm[off:off + n]
            if len(chunk) < n:
                chunk = np.pad(chunk, (0, n - len(chunk)))
            yield self.encode(chunk)


def resample(pcm: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linear resample is not good enough for voice; use ffmpeg."""
    if src_rate == dst_rate:
        return pcm.astype(np.int16)
    proc = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error",
         "-f", "s16le", "-ar", str(src_rate), "-ac", "1", "-i", "-",
         "-f", "s16le", "-ar", str(dst_rate), "-ac", "1", "-"],
        input=pcm.astype(np.int16).tobytes(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.int16)


# --- segment energy gate -----------------------------------------------------
# Silero VAD happily turns room noise into a "segment"; SenseVoice then invents a
# sentence and we run a whole agent turn on it. These thresholds are measured on
# this board (2026-10-27), not copied from rui:
# 2026-10-28 revision (task-26 step 2, real WAVs in tests/fixtures/segments/):
# 10 captured segments were all human speech, but the old 0.008 floor dropped the
# three quietest ones (rms 0.0053/0.0059/0.0064 -> "今天周几"/"今天天气怎么样").
# Loud white noise and fan noise produced *no* VAD segment at all, so Silero is
# already the real anti-noise filter; the RMS floor only needs to reject digital
# silence / channel noise. Lower it to 0.0025: below the quietest measured human
# segment (0.0053) and above a synthetic 0.0005 RMS silence. Hallucinated
# sentences that still pass are handled after ASR (`_valid_text` blacklist).
SEGMENT_RMS_FLOOR = 0.0025
SEGMENT_NOISE_MIN_SECONDS = 1.0  # sustained quiet only; short wakes still pass
SEGMENT_MIN_SECONDS = 0.2        # shorter blips never deserve an ASR call


def segment_rms(samples: np.ndarray) -> float:
    """RMS of a segment in [-1, 1]; accepts int16 PCM or silero float samples."""
    arr = np.asarray(samples)
    if arr.size == 0:
        return 0.0
    if arr.dtype == np.int16:
        arr = arr.astype(np.float32) / 32768.0
    else:
        arr = arr.astype(np.float32)
    return float(np.sqrt(np.mean(arr ** 2)))


def is_noise_segment(samples: np.ndarray, sample_rate: int = 16000) -> bool:
    """True when the VAD segment is too short or too quiet to send to ASR.

    Pure function (no I/O, no models) so the rule is unit-testable offline.
    A quiet but short segment (e.g. the two-syllable wake word, ~0.8 s) still
    passes: the minimum-duration condition only drops *sustained* low energy.
    """
    arr = np.asarray(samples)
    duration_s = arr.size / float(sample_rate)
    if duration_s < SEGMENT_MIN_SECONDS:
        return True
    return segment_rms(arr) < SEGMENT_RMS_FLOOR and duration_s >= SEGMENT_NOISE_MIN_SECONDS


# --- opt-in segment capture --------------------------------------------------
# The noise gate is being re-derived from real waveforms (task-26): historical
# logs only had rms/duration and RMS alone does not separate quiet speech from
# room noise. Capture is off by default and costs nothing when disabled.
CAPTURE_DIR = Path(__file__).resolve().parent.parent / "docs" / "segments"
CAPTURE_MAX_SEGMENTS = 60
CAPTURE_MAX_BYTES = 20 * 1024 * 1024      # 20 MB


class SegmentRecorder:
    """Write every handled VAD segment to docs/segments/<timestamp>/ as WAV.

    Files are named `kept|dropped-<rms>-<seconds>s.wav` so a later analysis can
    pair the waveform with the gate decision. Local only; capped at 60 segments
    or 20 MB, after which capture stops with one WARN line.
    """

    def __init__(self, root=None, max_segments: int = CAPTURE_MAX_SEGMENTS,
                 max_bytes: int = CAPTURE_MAX_BYTES):
        self.root = Path(root) if root is not None else CAPTURE_DIR
        self.max_segments = int(max_segments)
        self.max_bytes = int(max_bytes)
        self.count = 0
        self.bytes = 0
        self.stopped = False
        self.dir: Path | None = None

    def _ensure_dir(self) -> Path:
        if self.dir is None:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            self.dir = self.root / stamp
            self.dir.mkdir(parents=True, exist_ok=True)
        return self.dir

    def _stop(self) -> None:
        self.stopped = True
        print(f"[capture] WARN limit reached "
              f"({self.max_segments} segments / "
              f"{self.max_bytes / (1024 * 1024):.1f} MB); capture stopped",
              flush=True)

    def record(self, samples: np.ndarray, sample_rate: int, *, dropped: bool,
               rms: float | None = None) -> Path | None:
        """Save one segment; returns the path, or None when disabled/capped."""
        if self.stopped:
            return None
        arr = np.asarray(samples)
        if arr.dtype != np.int16:
            pcm = np.clip(arr.astype(np.float32) * 32768.0, -32768, 32767).astype(np.int16)
        else:
            pcm = arr
        size = pcm.nbytes + 44                    # 44-byte WAV header
        if self.count + 1 > self.max_segments or self.bytes + size > self.max_bytes:
            self._stop()
            return None
        duration = len(pcm) / float(sample_rate)
        if rms is None:
            rms = segment_rms(pcm)
        label = "dropped" if dropped else "kept"
        name = f"{label}-{rms:.4f}-{duration:.2f}s.wav"
        directory = self._ensure_dir()
        path = directory / name
        n = 2
        while path.exists():                      # same rms+duration in one second
            path = directory / f"{label}-{rms:.4f}-{duration:.2f}s-{n}.wav"
            n += 1
        with wave.open(str(path), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(int(sample_rate))
            fh.writeframes(pcm.tobytes())
        self.count += 1
        self.bytes += size
        return path


def build_segment_recorder(audio_cfg: dict) -> SegmentRecorder | None:
    """None (zero overhead) unless audio.capture_segments is true."""
    if not (audio_cfg or {}).get("capture_segments", False):
        return None
    return SegmentRecorder()


def build_vad(model_path: str, min_silence: float, min_speech: float,
              max_speech: float) -> sherpa_onnx.VoiceActivityDetector:
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(Path(model_path).expanduser())
    cfg.silero_vad.threshold = 0.4
    cfg.silero_vad.min_silence_duration = min_silence
    cfg.silero_vad.min_speech_duration = min_speech
    cfg.silero_vad.max_speech_duration = max_speech
    cfg.sample_rate = 16000
    return sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=30)


def pop_segments(vad) -> list[np.ndarray]:
    """Drain finished segments. Copy before pop(): pop() frees the buffer."""
    out = []
    while not vad.empty():
        seg = np.array(vad.front.samples, dtype=np.float32)
        vad.pop()
        out.append(seg)
    return out


class Asr:
    def __init__(self, model_dir: str, num_threads: int = 2):
        d = Path(model_dir).expanduser()
        cands = sorted(str(p) for p in d.glob("model*.onnx"))
        model = next((c for c in cands if "int8" in c), cands[0])
        self._rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=model, tokens=str(d / "tokens.txt"),
            num_threads=num_threads, use_itn=True, language="zh", debug=False)

    def transcribe(self, samples: np.ndarray, sample_rate: int = 16000) -> str:
        stream = self._rec.create_stream()
        stream.accept_waveform(sample_rate, samples.astype(np.float32))
        self._rec.decode_stream(stream)
        return stream.result.text.strip()
