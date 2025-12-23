"""Main speed control dialog with preview functionality."""
from __future__ import annotations

import os
import random
import shutil
import tempfile
from typing import Dict, List, Optional

from aqt import mw
from aqt.browser import Browser
from aqt.qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressDialog,
    Qt, QMessageBox, QAbstractItemView, QCheckBox
)
from aqt.sound import av_player
from anki.sound import SoundOrVideoTag
from aqt.utils import qconnect, showWarning

from ..audio.detector import detect_audio_in_cards, AudioFile, AudioDetectionResult, get_media_dir
from ..audio.processor import (
    process_audio_batch, generate_preview_file, find_ffmpeg,
    BatchProcessingResult
)
from ..core.card_processor import build_card_updates, apply_card_updates
from .completion_dialog import CompletionDialog


class SpeedUpAudioDialog(QDialog):
    """Main dialog for speeding up audio in selected cards."""

    def __init__(self, browser: Browser, card_ids: List[int]):
        super().__init__(browser)
        self.browser = browser
        self.card_ids = card_ids
        self.detection_result: Optional[AudioDetectionResult] = None
        self.preview_files: Dict[str, str] = {}  # Maps audio filename to temp preview path
        self.temp_dir = tempfile.mkdtemp(prefix="anki_audio_speed_")
        self.current_speed = 1.2
        self.skip_processed_checkbox: Optional[QCheckBox] = None

        self.setWindowTitle("Speed Up Audio")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)

        self._setup_ui()
        self._detect_audio()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Header
        header = QLabel(f"<b>Selected {len(self.card_ids)} cards</b>")
        layout.addWidget(header)

        # Speed slider section
        speed_layout = QHBoxLayout()
        speed_label = QLabel("Speed:")
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setMinimum(10)  # 1.0x
        self.speed_slider.setMaximum(30)  # 3.0x
        self.speed_slider.setValue(12)    # 1.2x default
        self.speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.speed_slider.setTickInterval(5)

        self.speed_value_label = QLabel("1.2x")
        self.speed_value_label.setMinimumWidth(40)

        qconnect(self.speed_slider.valueChanged, self._on_speed_changed)

        speed_layout.addWidget(speed_label)
        speed_layout.addWidget(self.speed_slider)
        speed_layout.addWidget(self.speed_value_label)
        layout.addLayout(speed_layout)

        # Statistics label
        self.stats_label = QLabel("Detecting audio files...")
        self.stats_label.setWordWrap(True)
        self.stats_label.setStyleSheet("""
            QLabel {
                background-color: palette(alternatebase);
                padding: 10px;
                border-radius: 5px;
                margin: 5px 0;
            }
        """)
        layout.addWidget(self.stats_label)

        # Preview table
        preview_label = QLabel("<b>Preview (random sample of cards with audio):</b>")
        layout.addWidget(preview_label)

        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(4)
        self.preview_table.setHorizontalHeaderLabels([
            "Card ID", "Audio File", "Play Original", "Play Sped Up"
        ])
        self.preview_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.preview_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.preview_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        layout.addWidget(self.preview_table)

        # Preview button
        preview_btn_layout = QHBoxLayout()
        self.preview_btn = QPushButton("Generate Preview")
        self.preview_btn.setEnabled(False)
        qconnect(self.preview_btn.clicked, self._generate_preview)
        preview_btn_layout.addStretch()
        preview_btn_layout.addWidget(self.preview_btn)
        layout.addLayout(preview_btn_layout)

        # Already processed warning (will be shown if needed)
        self.processed_warning = QLabel("")
        self.processed_warning.setStyleSheet("color: #cc7700; font-style: italic;")
        self.processed_warning.setWordWrap(True)
        self.processed_warning.hide()
        layout.addWidget(self.processed_warning)

        # Button row
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.ok_btn = QPushButton("OK")
        self.ok_btn.setEnabled(False)
        qconnect(self.ok_btn.clicked, self._on_ok)

        cancel_btn = QPushButton("Cancel")
        qconnect(cancel_btn.clicked, self.reject)

        button_layout.addWidget(self.ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def _on_speed_changed(self, value: int) -> None:
        """Handle speed slider change."""
        self.current_speed = value / 10.0
        self.speed_value_label.setText(f"{self.current_speed:.1f}x")

        # Clear preview files since speed changed
        self.preview_files.clear()
        self._update_preview_buttons()

    def _detect_audio(self) -> None:
        """Detect audio files in selected cards."""
        self.detection_result = detect_audio_in_cards(self.card_ids)

        if self.detection_result.total_audio_files == 0:
            showWarning(
                "No audio files found in the selected cards.",
                title="No Audio Found"
            )
            self.reject()
            return

        # Update statistics
        stats = self.detection_result
        stats_text = f"""
        <b>Audio Detection Results:</b><br>
        - Cards with audio: {stats.cards_with_audio}<br>
        - Cards without audio: {stats.cards_without_audio}<br>
        - Total audio files: {stats.total_audio_files}
        """

        if stats.already_processed_count > 0:
            stats_text += f"<br>- Already processed files: {stats.already_processed_count}"
            self.processed_warning.setText(
                f"Note: {stats.already_processed_count} files appear to have been "
                f"previously processed. You can skip them or re-process at new speed."
            )
            self.processed_warning.show()

            # Add checkbox to skip processed files
            self.skip_processed_checkbox = QCheckBox("Skip already processed files")
            self.skip_processed_checkbox.setChecked(True)
            # Insert before buttons
            self.layout().insertWidget(
                self.layout().count() - 1,
                self.skip_processed_checkbox
            )

        self.stats_label.setText(stats_text)

        # Enable buttons
        self.preview_btn.setEnabled(True)
        self.ok_btn.setEnabled(True)

        # Populate preview table
        self._populate_preview_table()

    def _populate_preview_table(self) -> None:
        """Populate the preview table with sample cards."""
        if not self.detection_result:
            return

        # Get unique audio files and sample 5-10
        unique_files: Dict[str, AudioFile] = {}
        for af in self.detection_result.audio_files:
            if af.filename not in unique_files:
                unique_files[af.filename] = af

        sample_size = min(10, max(5, len(unique_files)))
        sample_list = list(unique_files.values())
        sample = random.sample(sample_list, min(sample_size, len(sample_list)))

        self.preview_table.setRowCount(len(sample))

        for row, audio_file in enumerate(sample):
            # Card ID
            self.preview_table.setItem(
                row, 0,
                QTableWidgetItem(str(audio_file.card_id))
            )

            # Filename
            self.preview_table.setItem(
                row, 1,
                QTableWidgetItem(audio_file.filename)
            )

            # Play original button
            orig_btn = QPushButton("Play")
            qconnect(
                orig_btn.clicked,
                lambda checked, f=audio_file.filename: self._play_original(f)
            )
            self.preview_table.setCellWidget(row, 2, orig_btn)

            # Play preview button (disabled until preview generated)
            preview_btn = QPushButton("Play")
            preview_btn.setEnabled(False)
            preview_btn.setProperty("filename", audio_file.filename)
            qconnect(
                preview_btn.clicked,
                lambda checked, f=audio_file.filename: self._play_preview(f)
            )
            self.preview_table.setCellWidget(row, 3, preview_btn)

    def _play_original(self, filename: str) -> None:
        """Play the original audio file."""
        av_player.play_tags([SoundOrVideoTag(filename=filename)])

    def _play_preview(self, filename: str) -> None:
        """Play the preview (sped up) audio file."""
        if filename in self.preview_files:
            preview_path = self.preview_files[filename]
            # For temp files, we need to play from absolute path
            # Anki's av_player can handle absolute paths
            av_player.play_tags([SoundOrVideoTag(filename=preview_path)])

    def _update_preview_buttons(self) -> None:
        """Update the enabled state of preview play buttons."""
        for row in range(self.preview_table.rowCount()):
            btn = self.preview_table.cellWidget(row, 3)
            if btn:
                filename = btn.property("filename")
                btn.setEnabled(filename in self.preview_files)

    def _generate_preview(self) -> None:
        """Generate preview audio files."""
        if not self.detection_result:
            return

        # Check FFmpeg availability
        if not find_ffmpeg():
            showWarning(
                "FFmpeg not found. Please ensure FFmpeg is installed and in your PATH.",
                title="FFmpeg Required"
            )
            return

        # Get files from preview table
        preview_files_to_generate: List[AudioFile] = []
        for row in range(self.preview_table.rowCount()):
            filename_item = self.preview_table.item(row, 1)
            if filename_item:
                filename = filename_item.text()
                # Find the AudioFile object
                for af in self.detection_result.audio_files:
                    if af.filename == filename:
                        preview_files_to_generate.append(af)
                        break

        # Show progress
        progress = QProgressDialog(
            "Generating previews...", "Cancel", 0, len(preview_files_to_generate), self
        )
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.show()

        for idx, audio_file in enumerate(preview_files_to_generate):
            if progress.wasCanceled():
                break

            progress.setValue(idx)
            progress.setLabelText(f"Processing: {audio_file.filename}")
            mw.app.processEvents()

            preview_path = generate_preview_file(
                audio_file,
                self.current_speed,
                self.temp_dir
            )

            if preview_path:
                self.preview_files[audio_file.filename] = preview_path

        progress.setValue(len(preview_files_to_generate))

        # Update buttons
        self._update_preview_buttons()

    def _on_ok(self) -> None:
        """Handle OK button click - start processing."""
        if not self.detection_result:
            return

        # Determine which files to process
        files_to_process = self.detection_result.audio_files

        if self.skip_processed_checkbox and self.skip_processed_checkbox.isChecked():
            files_to_process = [
                af for af in files_to_process
                if not af.is_processed
            ]

        if not files_to_process:
            showWarning("No files to process after filtering.")
            return

        # Count unique files
        unique_count = len({af.filename for af in files_to_process})

        # Confirm
        result = QMessageBox.question(
            self,
            "Confirm Processing",
            f"This will process {unique_count} unique audio files at {self.current_speed:.1f}x speed.\n\n"
            f"Original files will be preserved.\n\n"
            f"Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if result != QMessageBox.StandardButton.Yes:
            return

        # Show progress dialog
        unique_files = list({af.filename: af for af in files_to_process}.values())

        progress = QProgressDialog(
            "Processing audio files...", "Cancel", 0, len(unique_files), self
        )
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.show()

        cancelled = False

        def progress_callback(current: int, total: int, message: str) -> None:
            progress.setValue(current)
            progress.setLabelText(message)
            mw.app.processEvents()

        def cancel_check() -> bool:
            nonlocal cancelled
            if progress.wasCanceled():
                cancelled = True
            return cancelled

        # Process audio files
        batch_result = process_audio_batch(
            unique_files,
            self.current_speed,
            progress_callback=progress_callback,
            cancel_check=cancel_check
        )

        progress.close()

        if cancelled:
            showWarning("Processing was cancelled.")
            return

        # Build file mapping for card updates
        file_mapping = {
            r.original_file: r.new_file
            for r in batch_result.successful
            if r.new_file
        }

        # Update cards
        if file_mapping:
            card_updates = build_card_updates(files_to_process, file_mapping)
            undo_record = apply_card_updates(card_updates)

            # Refresh browser to show changes
            self.browser.model.reset()

            # Show completion dialog
            completion = CompletionDialog(
                self,
                batch_result,
                undo_record,
                self.current_speed
            )
            completion.exec()

            # Refresh browser again if undo was applied
            if completion.undo_applied:
                self.browser.model.reset()
        else:
            showWarning("No files were successfully processed.")

        # Close main dialog
        self.accept()

    def closeEvent(self, event) -> None:
        """Clean up temp files on close."""
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass
        super().closeEvent(event)
