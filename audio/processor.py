"""Audio processing logic for pitch-preserving speed changes."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .detector import AudioFile, generate_speed_filename, get_media_dir


@dataclass
class ProcessingResult:
    """Result of processing a single audio file."""
    success: bool
    original_file: str
    new_file: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class BatchProcessingResult:
    """Result of processing multiple audio files."""
    successful: List[ProcessingResult] = field(default_factory=list)
    failed: List[ProcessingResult] = field(default_factory=list)
    total_processed: int = 0

    @property
    def success_count(self) -> int:
        return len(self.successful)

    @property
    def failure_count(self) -> int:
        return len(self.failed)


def find_ffmpeg() -> Optional[str]:
    """
    Find FFmpeg executable.

    Anki bundles FFmpeg, so we check common locations.
    """
    # Try system PATH first
    if shutil.which("ffmpeg"):
        return "ffmpeg"

    # Try Anki's bundled location (varies by platform)
    import sys
    if sys.platform == "darwin":
        # macOS: might be in Anki.app bundle or Homebrew
        possible_paths = [
            "/Applications/Anki.app/Contents/MacOS/ffmpeg",
            "/usr/local/bin/ffmpeg",
            "/opt/homebrew/bin/ffmpeg",
        ]
    elif sys.platform == "win32":
        possible_paths = [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Anki\ffmpeg.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Anki\ffmpeg.exe"),
        ]
    else:  # Linux
        possible_paths = [
            "/usr/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
        ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    return None


def build_atempo_filter(speed: float) -> str:
    """
    Build FFmpeg atempo filter chain for the given speed.

    The atempo filter works best in range [0.5, 2.0].
    For speeds > 2.0, chain multiple filters.
    """
    if 0.5 <= speed <= 2.0:
        return f"atempo={speed}"

    # For speeds > 2.0, chain filters
    filters = []
    remaining = speed

    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0

    if remaining >= 0.5:
        filters.append(f"atempo={remaining:.6f}")

    return ",".join(filters)


def get_output_codec_args(input_path: str) -> List[str]:
    """
    Get appropriate codec arguments based on input file type.
    Tries to preserve quality as much as possible.
    """
    ext = os.path.splitext(input_path.lower())[1]

    if ext == ".mp3":
        # High quality MP3
        return ["-acodec", "libmp3lame", "-q:a", "2"]
    elif ext == ".wav":
        # Keep as WAV
        return ["-acodec", "pcm_s16le"]
    elif ext == ".ogg":
        # Vorbis for OGG
        return ["-acodec", "libvorbis", "-q:a", "6"]
    elif ext == ".m4a":
        # AAC for M4A
        return ["-acodec", "aac", "-b:a", "192k"]
    elif ext in (".mp4", ".webm"):
        # For video files, just process audio, copy video
        return ["-acodec", "aac", "-b:a", "192k", "-vcodec", "copy"]
    else:
        # Default to MP3
        return ["-acodec", "libmp3lame", "-q:a", "2"]


def process_audio_ffmpeg(
    input_path: str,
    output_path: str,
    speed: float,
    ffmpeg_path: str = "ffmpeg"
) -> Tuple[bool, Optional[str]]:
    """
    Process audio file using FFmpeg.

    Args:
        input_path: Path to input audio file
        output_path: Path for output audio file
        speed: Speed multiplier (e.g., 1.2 for 20% faster)
        ffmpeg_path: Path to FFmpeg executable

    Returns:
        Tuple of (success, error_message)
    """
    filter_chain = build_atempo_filter(speed)
    codec_args = get_output_codec_args(input_path)

    cmd = [
        ffmpeg_path,
        "-y",  # Overwrite output without asking
        "-i", input_path,
        "-filter:a", filter_chain,
        *codec_args,
        output_path
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120  # 2 minute timeout per file
        )

        if result.returncode != 0:
            return False, f"FFmpeg error: {result.stderr[:500]}"

        # Verify output file was created
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 100:
            return False, "Output file not created or too small"

        return True, None

    except subprocess.TimeoutExpired:
        return False, "FFmpeg timed out"
    except Exception as e:
        return False, f"Error running FFmpeg: {str(e)}"


def process_audio_file(
    audio_file: AudioFile,
    speed: float,
    ffmpeg_path: str
) -> ProcessingResult:
    """
    Process a single audio file.

    Creates a new file with the speed suffix in Anki's media directory.
    """
    media_dir = get_media_dir()
    input_path = os.path.join(media_dir, audio_file.filename)

    # Check if input file exists
    if not os.path.exists(input_path):
        return ProcessingResult(
            success=False,
            original_file=audio_file.filename,
            error_message=f"File not found: {audio_file.filename}"
        )

    # Generate new filename
    new_filename = generate_speed_filename(audio_file.filename, speed)
    output_path = os.path.join(media_dir, new_filename)

    # Check if output already exists
    if os.path.exists(output_path):
        # File already exists, consider it a success
        return ProcessingResult(
            success=True,
            original_file=audio_file.filename,
            new_file=new_filename
        )

    # Process the audio
    success, error = process_audio_ffmpeg(input_path, output_path, speed, ffmpeg_path)

    if success:
        return ProcessingResult(
            success=True,
            original_file=audio_file.filename,
            new_file=new_filename
        )
    else:
        return ProcessingResult(
            success=False,
            original_file=audio_file.filename,
            error_message=error
        )


def process_audio_batch(
    audio_files: List[AudioFile],
    speed: float,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None
) -> BatchProcessingResult:
    """
    Process multiple audio files.

    Args:
        audio_files: List of AudioFile objects to process
        speed: Speed multiplier
        progress_callback: Optional callback(current, total, message)
        cancel_check: Optional function returning True if cancelled

    Returns:
        BatchProcessingResult with all results
    """
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        # Return all as failed
        return BatchProcessingResult(
            successful=[],
            failed=[
                ProcessingResult(
                    success=False,
                    original_file=af.filename,
                    error_message="FFmpeg not found"
                ) for af in audio_files
            ],
            total_processed=0
        )

    successful: List[ProcessingResult] = []
    failed: List[ProcessingResult] = []

    # Deduplicate files (same file might appear in multiple cards)
    unique_files: Dict[str, AudioFile] = {}
    for af in audio_files:
        if af.filename not in unique_files:
            unique_files[af.filename] = af

    total = len(unique_files)

    for idx, (filename, audio_file) in enumerate(unique_files.items()):
        # Check for cancellation
        if cancel_check and cancel_check():
            break

        # Update progress
        if progress_callback:
            progress_callback(idx + 1, total, f"Processing: {filename}")

        result = process_audio_file(audio_file, speed, ffmpeg_path)

        if result.success:
            successful.append(result)
        else:
            failed.append(result)

    return BatchProcessingResult(
        successful=successful,
        failed=failed,
        total_processed=len(successful) + len(failed)
    )


def generate_preview_file(
    audio_file: AudioFile,
    speed: float,
    temp_dir: Optional[str] = None
) -> Optional[str]:
    """
    Generate a temporary preview file.

    Args:
        audio_file: The audio file to preview
        speed: Speed multiplier
        temp_dir: Optional temp directory (uses system temp if None)

    Returns:
        Path to temporary preview file, or None on failure
    """
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        return None

    media_dir = get_media_dir()
    input_path = os.path.join(media_dir, audio_file.filename)

    if not os.path.exists(input_path):
        return None

    # Create temp file with same extension
    ext = os.path.splitext(audio_file.filename)[1]
    if temp_dir:
        os.makedirs(temp_dir, exist_ok=True)
        output_path = os.path.join(
            temp_dir,
            f"preview_{speed:.1f}x_{os.path.basename(audio_file.filename)}"
        )
    else:
        fd, output_path = tempfile.mkstemp(suffix=ext)
        os.close(fd)

    success, _ = process_audio_ffmpeg(input_path, output_path, speed, ffmpeg_path)

    return output_path if success else None
