"""Audio File Speed Control - Anki Addon

Allows users to speed up audio files in selected cards with pitch preservation.
"""
from __future__ import annotations

from aqt import gui_hooks, mw
from aqt.browser import Browser
from aqt.qt import QAction
from aqt.utils import qconnect, showInfo


def on_speed_up_audio_browser(browser: Browser) -> None:
    """Handle menu action from browser."""
    selected_cards = browser.selectedCards()
    if not selected_cards:
        showInfo("No cards selected. Please select cards to process.")
        return

    from .ui.speed_dialog import SpeedUpAudioDialog
    dialog = SpeedUpAudioDialog(browser, selected_cards)
    dialog.exec()


def setup_browser_menu(browser: Browser) -> None:
    """Add menu item to browser's Edit menu."""
    action = QAction("Speed Up Audio...", browser)
    qconnect(action.triggered, lambda: on_speed_up_audio_browser(browser))
    browser.form.menuEdit.addSeparator()
    browser.form.menuEdit.addAction(action)


# Register hook for browser menu
gui_hooks.browser_menus_did_init.append(setup_browser_menu)
