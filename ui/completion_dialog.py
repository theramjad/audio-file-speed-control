"""Completion dialog showing summary and undo option."""
from __future__ import annotations

from aqt.qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QMessageBox
)
from aqt.utils import qconnect, showInfo

from ..audio.processor import BatchProcessingResult
from ..core.card_processor import UndoRecord, revert_card_updates


class CompletionDialog(QDialog):
    """Dialog showing processing completion summary with undo option."""

    def __init__(
        self,
        parent,
        batch_result: BatchProcessingResult,
        undo_record: UndoRecord,
        speed: float
    ):
        super().__init__(parent)
        self.batch_result = batch_result
        self.undo_record = undo_record
        self.speed = speed
        self.undo_applied = False

        self.setWindowTitle("Processing Complete")
        self.setMinimumWidth(500)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Summary header
        header = QLabel(f"<h3>Audio Speed Up Complete ({self.speed:.1f}x)</h3>")
        layout.addWidget(header)

        # Statistics
        stats_text = f"""
        <b>Summary:</b><br>
        - Successfully processed: {self.batch_result.success_count} files<br>
        - Failed: {self.batch_result.failure_count} files<br>
        - Cards updated: {len(self.undo_record.card_updates)}<br>
        """

        stats_label = QLabel(stats_text)
        stats_label.setWordWrap(True)
        stats_label.setStyleSheet("""
            QLabel {
                background-color: palette(alternatebase);
                padding: 10px;
                border-radius: 5px;
            }
        """)
        layout.addWidget(stats_label)

        # Show failures if any
        if self.batch_result.failed:
            failure_label = QLabel("<b>Failed files:</b>")
            layout.addWidget(failure_label)

            failure_text = QTextEdit()
            failure_text.setReadOnly(True)
            failure_text.setMaximumHeight(100)

            failures = "\n".join([
                f"- {r.original_file}: {r.error_message}"
                for r in self.batch_result.failed
            ])
            failure_text.setPlainText(failures)
            layout.addWidget(failure_text)

        # Note about original files
        note_label = QLabel(
            "<i>Note: Original audio files have been preserved. "
            "You can use Anki's 'Check Media' to find and delete unused files later.</i>"
        )
        note_label.setWordWrap(True)
        note_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(note_label)

        # Buttons
        button_layout = QHBoxLayout()

        self.undo_btn = QPushButton("Undo Changes")
        qconnect(self.undo_btn.clicked, self._on_undo)

        close_btn = QPushButton("Close")
        qconnect(close_btn.clicked, self.accept)

        button_layout.addWidget(self.undo_btn)
        button_layout.addStretch()
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _on_undo(self) -> None:
        """Handle undo button click."""
        result = QMessageBox.question(
            self,
            "Confirm Undo",
            "This will revert all card references back to the original audio files.\n\n"
            "Note: The newly created audio files will NOT be deleted. "
            "You can use Anki's 'Check Media' to remove them.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if result != QMessageBox.StandardButton.Yes:
            return

        try:
            revert_card_updates(self.undo_record)
            self.undo_applied = True
            self.undo_btn.setEnabled(False)
            self.undo_btn.setText("Undo Applied")
            showInfo("Card references have been reverted to original audio files.")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Undo Failed",
                f"Failed to undo changes: {str(e)}"
            )
