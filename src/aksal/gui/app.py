"""A very simple PyQt6 front end for AKSAL's two phases.

    pick video + lyrics -> Run Phase 1 -> fix lines in Aegisub -> Run Phase 2

Runs the same ``aksal.cli.main`` the command line uses, on a background
thread so the window stays responsive, and streams its printed log into a
console pane.
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QRadioButton, QToolButton, QVBoxLayout, QWidget,
)

from . import params

VIDEO_FILTER = "Video files (*.mkv *.mp4 *.avi *.mov *.webm *.ts);;All files (*)"
LYRICS_FILTER = ("Aegisub subtitle (*.ass);;Lyrics text (*.txt);;"
                  "All files (*)")


class _SignalStream:
    """A file-like object that forwards writes to a Qt signal.

    ``cli.main`` prints through this while it runs, so the log pane shows
    exactly what the CLI would have shown in a terminal.
    """

    def __init__(self, emit):
        self._emit = emit

    def write(self, text: str) -> None:
        if text:
            self._emit(text)

    def flush(self) -> None:
        pass

    def reconfigure(self, *_args, **_kwargs) -> None:
        pass

    def isatty(self) -> bool:
        return False


class RunnerThread(QThread):
    output = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, argv: list[str], parent=None):
        super().__init__(parent)
        self.argv = argv

    def run(self) -> None:
        from aksal import cli

        stream = _SignalStream(self.output.emit)
        try:
            with contextlib.redirect_stdout(stream), \
                 contextlib.redirect_stderr(stream):
                cli.main(self.argv)
            self.done.emit(True, "")
        except SystemExit as exc:
            ok = exc.code in (None, 0)
            self.done.emit(ok, "" if ok else str(exc.code))
        except Exception as exc:  # surfaced in the log pane, not a crash
            self.done.emit(False, f"{type(exc).__name__}: {exc}")


def _browse_into(parent, edit: QLineEdit, *, directory=False, filter_=None):
    if directory:
        path = QFileDialog.getExistingDirectory(parent, "Select folder",
                                                edit.text())
    else:
        path, _ = QFileDialog.getOpenFileName(parent, "Select file",
                                              edit.text(), filter_ or "")
    if path:
        edit.setText(path)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AKSAL")
        self.resize(760, 640)

        self.thread: RunnerThread | None = None
        self.current_lines_path: Path | None = None
        self.has_project = False

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.status_label = QLabel(
            "1. Pick a video and lyrics.  2. Run Phase 1.  "
            "3. Fix the lines in Aegisub.  4. Run Phase 2.")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        root.addLayout(self._file_row(
            "Video", "video_edit", VIDEO_FILTER, self._on_video_changed))
        root.addLayout(self._file_row(
            "Lyrics / timed lines", "lyrics_edit", LYRICS_FILTER,
            self._on_lyrics_changed))

        mode_row = QHBoxLayout()
        self.radio_untimed = QRadioButton("Untimed lyrics -> run Phase 1")
        self.radio_timed = QRadioButton("Already-timed lines -> Phase 2 only")
        self.radio_untimed.setChecked(True)
        self.radio_untimed.toggled.connect(self._update_buttons)
        mode_row.addWidget(self.radio_untimed)
        mode_row.addWidget(self.radio_timed)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        root.addLayout(self._file_row(
            "Reference track (optional)", "reference_edit",
            "Audio files (*.flac *.wav *.mp3 *.m4a);;All files (*)"))
        root.addLayout(self._file_row(
            "Output directory (optional)", "output_dir_edit", None,
            directory=True))

        timing_row = QHBoxLayout()
        self.song_start_edit = QLineEdit()
        self.song_start_edit.setPlaceholderText("song start, e.g. 0:36")
        self.duration_edit = QLineEdit()
        self.duration_edit.setPlaceholderText("duration, e.g. 90 (default 92s)")
        timing_row.addWidget(QLabel("Song start"))
        timing_row.addWidget(self.song_start_edit)
        timing_row.addWidget(QLabel("Duration"))
        timing_row.addWidget(self.duration_edit)
        root.addLayout(timing_row)

        root.addWidget(self._advanced_box())

        button_row = QHBoxLayout()
        self.phase1_btn = QPushButton("Run Phase 1")
        self.phase1_btn.clicked.connect(self._run_phase1)
        self.phase2_btn = QPushButton("Run Phase 2")
        self.phase2_btn.clicked.connect(self._run_phase2)
        self.open_lines_btn = QPushButton("Open lines file")
        self.open_lines_btn.clicked.connect(self._open_lines_file)
        self.open_lines_btn.setEnabled(False)
        button_row.addWidget(self.phase1_btn)
        button_row.addWidget(self.phase2_btn)
        button_row.addWidget(self.open_lines_btn)
        root.addLayout(button_row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log.setStyleSheet("font-family: Consolas, monospace;")
        root.addWidget(self.log, 1)

        self._update_buttons()

    # -- layout helpers ----------------------------------------------------

    def _file_row(self, label, attr, filter_, on_change=None, *,
                  directory=False):
        edit = QLineEdit()
        setattr(self, attr, edit)
        browse = QPushButton("Browse...")
        browse.clicked.connect(
            lambda: _browse_into(self, edit, directory=directory,
                                 filter_=filter_))
        if on_change:
            edit.textChanged.connect(on_change)
        edit.textChanged.connect(self._update_buttons)
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addWidget(edit, 1)
        row.addWidget(browse)
        return row

    def _advanced_box(self) -> QWidget:
        toggle = QToolButton()
        toggle.setText("Advanced options")
        toggle.setCheckable(True)
        toggle.setArrowType(Qt.ArrowType.RightArrow)

        box = QGroupBox()
        box.setVisible(False)
        form = QVBoxLayout(box)

        analyser_row = QHBoxLayout()
        self.analyser_combo = QComboBox()
        self.analyser_combo.addItems(["ichiran", "unidic"])
        self.insert_romaji_check = QCheckBox("Insert romaji hints (Phase 1)")
        self.insert_romaji_check.setChecked(True)
        self.separate_vocals_check = QCheckBox("Isolate vocals (slower)")
        analyser_row.addWidget(QLabel("Analyser"))
        analyser_row.addWidget(self.analyser_combo)
        analyser_row.addWidget(self.insert_romaji_check)
        analyser_row.addWidget(self.separate_vocals_check)
        analyser_row.addStretch(1)
        form.addLayout(analyser_row)

        phase2_row = QHBoxLayout()
        self.time_against_combo = QComboBox()
        self.time_against_combo.addItems(["video", "reference"])
        self.group_combo = QComboBox()
        self.group_combo.addItems(["syllable", "word"])
        self.tracks_jp_check = QCheckBox("JP track")
        self.tracks_jp_check.setChecked(True)
        self.tracks_romaji_check = QCheckBox("Romaji track")
        self.tracks_romaji_check.setChecked(True)
        phase2_row.addWidget(QLabel("Time Phase 2 against"))
        phase2_row.addWidget(self.time_against_combo)
        phase2_row.addWidget(QLabel("Group by"))
        phase2_row.addWidget(self.group_combo)
        phase2_row.addWidget(self.tracks_jp_check)
        phase2_row.addWidget(self.tracks_romaji_check)
        phase2_row.addStretch(1)
        form.addLayout(phase2_row)

        def _toggle(checked):
            box.setVisible(checked)
            toggle.setArrowType(
                Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

        toggle.toggled.connect(_toggle)

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(toggle)
        layout.addWidget(box)
        return wrapper

    # -- reactions -----------------------------------------------------

    def _on_video_changed(self, _text: str) -> None:
        self.current_lines_path = None
        self.has_project = False

    def _on_lyrics_changed(self, text: str) -> None:
        self.current_lines_path = None
        self.has_project = False
        timed = params.looks_timed(text)
        block = self.radio_timed.blockSignals(True)
        self.radio_timed.setChecked(timed)
        self.radio_untimed.setChecked(not timed)
        self.radio_timed.blockSignals(block)

    def _update_buttons(self) -> None:
        running = self.thread is not None
        have_video = bool(self.video_edit.text().strip())
        have_lyrics = bool(self.lyrics_edit.text().strip())
        untimed = self.radio_untimed.isChecked()

        self.phase1_btn.setEnabled(
            not running and untimed and have_video and have_lyrics)
        self.phase2_btn.setEnabled(
            not running and have_video and have_lyrics and (
                self.current_lines_path is not None or not untimed))

    # -- phase 1 ---------------------------------------------------------

    def _run_phase1(self) -> None:
        video = Path(self.video_edit.text().strip())
        if not video.exists():
            QMessageBox.warning(self, "AKSAL", f"video not found: {video}")
            return

        form = params.Phase1Form(
            video=str(video),
            lyrics=self.lyrics_edit.text().strip(),
            output_dir=self.output_dir_edit.text().strip(),
            reference=self.reference_edit.text().strip(),
            song_start=self.song_start_edit.text().strip(),
            duration=self.duration_edit.text().strip(),
            analyser=self.analyser_combo.currentText(),
            insert_romaji=self.insert_romaji_check.isChecked(),
            separate_vocals=self.separate_vocals_check.isChecked(),
        )
        self._start(form.argv(), self._on_phase1_done)

    def _on_phase1_done(self, ok: bool, message: str) -> None:
        if not ok:
            self.status_label.setText("Phase 1 failed -- see the log below.")
            if message:
                QMessageBox.critical(self, "Phase 1 failed", message)
            return

        video = Path(self.video_edit.text().strip())
        output_dir = self.output_dir_edit.text().strip()
        lines_path = params.default_lines_path(
            video, Path(output_dir) if output_dir else None)
        self.current_lines_path = lines_path
        self.has_project = True
        self.open_lines_btn.setEnabled(True)
        self.status_label.setText(
            f"Phase 1 done. Open {lines_path} in Aegisub, fix the line "
            "timings, save, then click Run Phase 2.")

    # -- phase 2 -----------------------------------------------------------

    def _run_phase2(self) -> None:
        if self.current_lines_path is not None:
            lines_path = self.current_lines_path
            has_project = self.has_project
        else:
            lines_path = Path(self.lyrics_edit.text().strip())
            if not lines_path.exists():
                QMessageBox.warning(
                    self, "AKSAL", f"lines file not found: {lines_path}")
                return
            has_project = params.has_existing_project(lines_path)

        tracks = tuple(
            t for t, checked in (
                ("jp", self.tracks_jp_check.isChecked()),
                ("romaji", self.tracks_romaji_check.isChecked()),
            ) if checked)

        form = params.Phase2Form(
            lines=str(lines_path),
            has_project=has_project,
            video=self.video_edit.text().strip(),
            reference=self.reference_edit.text().strip(),
            output_dir=self.output_dir_edit.text().strip(),
            time_against=self.time_against_combo.currentText(),
            group=self.group_combo.currentText(),
            tracks=tracks,
            analyser=self.analyser_combo.currentText(),
            separate_vocals=self.separate_vocals_check.isChecked(),
        )
        self._start(form.argv(), self._on_phase2_done)

    def _on_phase2_done(self, ok: bool, message: str) -> None:
        if ok:
            self.status_label.setText(
                "Phase 2 done -- karaoke written next to the lines file.")
        else:
            self.status_label.setText("Phase 2 failed -- see the log below.")
            if message:
                QMessageBox.critical(self, "Phase 2 failed", message)

    # -- shared run plumbing -------------------------------------------------

    def _start(self, argv: list[str], on_done) -> None:
        self.log.appendPlainText(f"$ aksal {' '.join(argv)}\n")
        self.thread = RunnerThread(argv, self)
        self.thread.output.connect(self._append_log)

        def _finished(ok: bool, message: str) -> None:
            on_done(ok, message)
            self.thread = None
            self._update_buttons()

        self.thread.done.connect(_finished)
        self._update_buttons()
        self.thread.start()

    def _append_log(self, text: str) -> None:
        cursor = self.log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.log.setTextCursor(cursor)
        self.log.insertPlainText(text)
        self.log.ensureCursorVisible()

    def _open_lines_file(self) -> None:
        if self.current_lines_path is not None:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self.current_lines_path)))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.thread is not None:
            QMessageBox.warning(
                self, "AKSAL", "A phase is still running -- please wait "
                "for it to finish before closing.")
            event.ignore()
            return
        event.accept()


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
