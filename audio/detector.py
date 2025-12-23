"""Audio file detection and pattern matching in card fields."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Set

from aqt import mw

# Regex pattern to match [sound:filename] tags
SOUND_TAG_PATTERN = re.compile(r'\[sound:([^\]]+)\]')

# Pattern to detect already-processed files
# Matches: filename_1.2x.mp3, filename_2.0x.wav, etc.
SPEED_PATTERN = re.compile(r'_(\d+\.\d+)x\.([a-zA-Z0-9]+)$')

# Supported audio/video formats
SUPPORTED_FORMATS = {'.mp3', '.wav', '.ogg', '.m4a', '.mp4', '.webm'}


@dataclass
class AudioFile:
    """Represents an audio file found in a card."""
    filename: str
    field_index: int
    card_id: int
    note_id: int
    original_tag: str  # The full [sound:xxx] tag
    is_processed: bool = False
    original_speed: Optional[float] = None


@dataclass
class AudioDetectionResult:
    """Result of audio detection across selected cards."""
    audio_files: List[AudioFile] = field(default_factory=list)
    cards_with_audio: int = 0
    cards_without_audio: int = 0
    total_audio_files: int = 0
    already_processed_count: int = 0


def get_media_dir() -> str:
    """Get the path to Anki's media directory."""
    return os.path.join(mw.pm.profileFolder(), "collection.media")


def is_supported_format(filename: str) -> bool:
    """Check if the file has a supported audio format."""
    ext = os.path.splitext(filename.lower())[1]
    return ext in SUPPORTED_FORMATS


def parse_speed_from_filename(filename: str) -> Optional[float]:
    """
    Extract speed multiplier from filename if it was previously processed.

    Returns:
        The speed multiplier (e.g., 1.2) or None if not a processed file.
    """
    match = SPEED_PATTERN.search(filename)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def extract_sound_tags(field_content: str) -> List[str]:
    """Extract all [sound:xxx] tags from a field."""
    return SOUND_TAG_PATTERN.findall(field_content)


def detect_audio_in_cards(card_ids: List[int]) -> AudioDetectionResult:
    """
    Detect all audio files in the selected cards.

    Args:
        card_ids: List of card IDs to scan

    Returns:
        AudioDetectionResult with detected audio files
    """
    audio_files: List[AudioFile] = []
    cards_with_audio: Set[int] = set()
    already_processed = 0

    for card_id in card_ids:
        card = mw.col.get_card(card_id)
        note = card.note()
        note_id = note.id

        for field_idx, field_content in enumerate(note.fields):
            sound_tags = extract_sound_tags(field_content)

            for filename in sound_tags:
                if not is_supported_format(filename):
                    continue

                # Check if already processed
                existing_speed = parse_speed_from_filename(filename)
                is_processed = existing_speed is not None

                if is_processed:
                    already_processed += 1

                audio_files.append(AudioFile(
                    filename=filename,
                    field_index=field_idx,
                    card_id=card_id,
                    note_id=note_id,
                    original_tag=f"[sound:{filename}]",
                    is_processed=is_processed,
                    original_speed=existing_speed
                ))
                cards_with_audio.add(card_id)

    return AudioDetectionResult(
        audio_files=audio_files,
        cards_with_audio=len(cards_with_audio),
        cards_without_audio=len(card_ids) - len(cards_with_audio),
        total_audio_files=len(audio_files),
        already_processed_count=already_processed
    )


def generate_speed_filename(original: str, speed: float) -> str:
    """
    Generate a new filename with speed indicator.

    Example: "audio.mp3" -> "audio_1.2x.mp3"
    """
    base, ext = os.path.splitext(original)

    # Remove existing speed suffix if present
    existing_match = SPEED_PATTERN.search(base + ext)
    if existing_match:
        # Find where the speed suffix starts in the base
        base_with_ext = base + ext
        suffix_start = existing_match.start()
        # Reconstruct base without the speed suffix
        base = base_with_ext[:suffix_start]

    return f"{base}_{speed:.1f}x{ext}"
