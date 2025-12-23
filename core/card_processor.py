"""Card field parsing and updating logic."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from aqt import mw


@dataclass
class CardUpdate:
    """Represents an update to be made to a card."""
    card_id: int
    note_id: int
    field_index: int
    old_tag: str
    new_tag: str


@dataclass
class UndoRecord:
    """Record of changes made for undo functionality."""
    card_updates: List[CardUpdate] = field(default_factory=list)
    processed_files: Dict[str, str] = field(default_factory=dict)  # original -> new filename


def build_card_updates(
    audio_files: List,  # List[AudioFile]
    file_mapping: Dict[str, str]  # original filename -> new filename
) -> List[CardUpdate]:
    """
    Build list of card updates based on processed files.

    Args:
        audio_files: List of detected audio files
        file_mapping: Mapping of original to new filenames

    Returns:
        List of CardUpdate objects
    """
    updates: List[CardUpdate] = []

    for af in audio_files:
        if af.filename in file_mapping:
            new_filename = file_mapping[af.filename]
            updates.append(CardUpdate(
                card_id=af.card_id,
                note_id=af.note_id,
                field_index=af.field_index,
                old_tag=af.original_tag,
                new_tag=f"[sound:{new_filename}]"
            ))

    return updates


def apply_card_updates(updates: List[CardUpdate]) -> UndoRecord:
    """
    Apply updates to cards in the database.

    Groups updates by note to minimize database operations.

    Returns:
        UndoRecord for reverting changes
    """
    # Group updates by note
    note_updates: Dict[int, List[CardUpdate]] = {}
    for update in updates:
        if update.note_id not in note_updates:
            note_updates[update.note_id] = []
        note_updates[update.note_id].append(update)

    # Track file mappings for undo
    file_mapping: Dict[str, str] = {}
    applied_updates: List[CardUpdate] = []

    for note_id, note_update_list in note_updates.items():
        note = mw.col.get_note(note_id)

        for update in note_update_list:
            # Update the field
            old_content = note.fields[update.field_index]
            new_content = old_content.replace(update.old_tag, update.new_tag)
            note.fields[update.field_index] = new_content

            # Track for undo
            old_filename = update.old_tag[7:-1]  # Extract from [sound:xxx]
            new_filename = update.new_tag[7:-1]
            file_mapping[old_filename] = new_filename
            applied_updates.append(update)

        # Save the note
        mw.col.update_note(note)

    return UndoRecord(
        card_updates=applied_updates,
        processed_files=file_mapping
    )


def revert_card_updates(undo_record: UndoRecord) -> None:
    """
    Revert card updates using the undo record.

    Note: This only reverts the card references, not the created files.
    """
    # Group by note
    note_updates: Dict[int, List[CardUpdate]] = {}
    for update in undo_record.card_updates:
        if update.note_id not in note_updates:
            note_updates[update.note_id] = []
        note_updates[update.note_id].append(update)

    for note_id, updates in note_updates.items():
        note = mw.col.get_note(note_id)

        for update in updates:
            # Revert the field (swap old and new)
            old_content = note.fields[update.field_index]
            new_content = old_content.replace(update.new_tag, update.old_tag)
            note.fields[update.field_index] = new_content

        mw.col.update_note(note)
