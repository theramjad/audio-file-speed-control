# Audio File Speed Control

An Anki add-on that permanently speeds up audio files in your cards with pitch preservation, so they play back faster everywhere — not just during review.

![Screenshot](https://github.com/theramjad/audio-file-speed-control/blob/main/resources/screenshot-1.png?raw=true)

## How It Works

Select cards in the browser, pick a speed, preview, and confirm. The add-on re-encodes your audio files using FFmpeg's `atempo` filter and updates your card references to point to the new files. Originals are always preserved.

## Requirements

- Anki 23.10+
- FFmpeg in your PATH
  - macOS: `brew install ffmpeg`
  - Windows: [ffmpeg.org/download](https://ffmpeg.org/download.html)

## Usage

1. Open the **Card Browser**
2. Select cards with audio
3. **Edit > "Speed Up Audio..."**
4. Set speed, optionally click **Generate Preview** to hear a sample
5. Click **OK** to process

## Features

- Pitch-preserving speed change via FFmpeg `atempo`
- Preview sped-up audio before committing
- Batch processing with progress bar and cancellation
- Skip already-processed files
- One-click undo (reverts card references)
- Supports MP3, WAV, OGG, M4A, MP4, WebM

## License

MIT
