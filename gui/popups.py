from typing import Callable, Optional

import chess
import pandas as pd
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, QFormLayout, QLineEdit,
                                QCheckBox, QComboBox, QHBoxLayout, QWidget, QDialogButtonBox, QFileDialog,
                                QTableWidget, QTableWidgetItem, QProgressBar)
from PySide6.QtGui import QIcon, QPixmap

from utils.constants import images, QUEENW, ROOKW, BISHOPW, KNIGHTW, QUEENB, ROOKB, BISHOPB, KNIGHTB


class TextboxPopup(QDialog):
    def __init__(self, title: str, message: str, parent=None) -> None:
        super(TextboxPopup, self).__init__(parent)
        self.setWindowTitle(title)

        self.label = QLabel(message, self)
        self.ok_button = QPushButton("OK", self)
        self.ok_button.clicked.connect(self.accept)

        self.layout = QVBoxLayout(self)
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.ok_button)
        self.setLayout(self.layout)


class SettingsDialog(QDialog):
    """
    Schema-driven settings form, replacing utils.settings.Settings' old PySimpleGUI prompt.

    Mirrors the 4 input kinds the schema supports: "str" -> QLineEdit, "Path" -> QLineEdit
    with a Browse button, "bool" -> QCheckBox, and a list of options -> QComboBox.
    """

    def __init__(self, schema: dict, values: dict, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._inputs = {}

        form = QFormLayout(self)
        for key, input_type in sorted(schema.items()):
            current = values.get(key, "")
            if input_type == "Path":
                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                line_edit = QLineEdit(str(current))
                browse_button = QPushButton("Browse…")
                browse_button.clicked.connect(lambda _checked=False, le=line_edit: self._browse(le))
                row_layout.addWidget(line_edit)
                row_layout.addWidget(browse_button)
                form.addRow(key, row)
                self._inputs[key] = line_edit
            elif input_type == "str":
                line_edit = QLineEdit(str(current))
                form.addRow(key, line_edit)
                self._inputs[key] = line_edit
            elif input_type == "bool":
                checkbox = QCheckBox()
                checkbox.setChecked(bool(current))
                form.addRow(key, checkbox)
                self._inputs[key] = checkbox
            elif isinstance(input_type, list):
                combo = QComboBox()
                combo.addItems(input_type)
                if current in input_type:
                    combo.setCurrentText(current)
                form.addRow(key, combo)
                self._inputs[key] = combo
            else:
                raise NotImplementedError(f"Unsupported settings input type: {input_type!r}")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        form.addRow(buttons)

    def _browse(self, line_edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select file")
        if path:
            line_edit.setText(path)

    def values(self) -> dict:
        out = {}
        for key, widget in self._inputs.items():
            if isinstance(widget, QLineEdit):
                out[key] = widget.text()
            elif isinstance(widget, QCheckBox):
                out[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                out[key] = widget.currentText()
        return out


class PromotionPickerDialog(QDialog):
    """4 piece-image buttons; replaces utils.promotion_select_window.select_promotion_piece."""

    _PIECES = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]
    _WHITE_IMAGES = [QUEENW, ROOKW, BISHOPW, KNIGHTW]
    _BLACK_IMAGES = [QUEENB, ROOKB, BISHOPB, KNIGHTB]

    def __init__(self, stm: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Promote to…")
        self.selected_piece = None

        layout = QHBoxLayout(self)
        image_keys = self._WHITE_IMAGES if stm else self._BLACK_IMAGES
        for piece, image_key in zip(self._PIECES, image_keys):
            button = QPushButton()
            button.setIcon(QIcon(QPixmap(images[image_key])))
            button.clicked.connect(lambda _checked=False, p=piece: self._pick(p))
            layout.addWidget(button)

    def _pick(self, piece: int) -> None:
        self.selected_piece = piece
        self.accept()

    @classmethod
    def get_promotion_piece(cls, stm: bool, parent=None) -> int:
        """
        Defaults to chess.QUEEN if the dialog is dismissed without a pick, matching
        the old select_promotion_piece's "defaulted to queen" fallback.
        """
        dialog = cls(stm=stm, parent=parent)
        dialog.exec()
        if dialog.selected_piece is None:
            print('User did not select a promotion piece, defaulted to queen.')
            return chess.QUEEN
        return dialog.selected_piece


class TablePopup(QDialog):
    """
    Generic sortable table dialog backed by a DataFrame; shared by all Data-menu popups.

    If on_row_picked is given, double-clicking a row calls it with that row (a pandas
    Series) and closes the dialog.
    """

    def __init__(self,
                title: str,
                dataframe: pd.DataFrame,
                on_row_picked: Optional[Callable[[pd.Series], None]] = None,
                hidden_columns: tuple = (),
                parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._dataframe = dataframe
        self._on_row_picked = on_row_picked

        visible_columns = [c for c in dataframe.columns if c not in hidden_columns]
        table = QTableWidget(len(dataframe), len(visible_columns))
        table.setHorizontalHeaderLabels(visible_columns)
        for row_i in range(len(dataframe)):
            for col_i, col_name in enumerate(visible_columns):
                table.setItem(row_i, col_i, QTableWidgetItem(str(dataframe.iloc[row_i][col_name])))
        table.setSortingEnabled(True)
        if on_row_picked is not None:
            table.cellDoubleClicked.connect(self._row_double_clicked)

        layout = QVBoxLayout(self)
        layout.addWidget(table)
        self.resize(900, 500)

    def _row_double_clicked(self, row: int, _column: int) -> None:
        self._on_row_picked(self._dataframe.iloc[row])
        self.accept()


class DownloadProgressDialog(QDialog):
    """
    A progress bar shown while games download in the background.

    Determinate (a filling bar, 0 up to `maximum`) when the number of games to
    download is known ahead of time; indeterminate (a busy/marquee bar) when it
    isn't - Lichess streams games one at a time with no upfront total count, so
    "download all" can only show a running tally, not a percentage.
    """

    def __init__(self, title: str, maximum: int = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        self.status_label = QLabel("Starting download…")
        self.progress_bar = QProgressBar()
        if maximum is not None:
            self.progress_bar.setRange(0, maximum)
        else:
            self.progress_bar.setRange(0, 0)  # indeterminate

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)

    def update_progress(self, games_added: int) -> None:
        if self.progress_bar.maximum() > 0:
            self.progress_bar.setValue(games_added)
        self.status_label.setText(f"{games_added} game{'s' if games_added != 1 else ''} downloaded…")

    def show_failure(self, message: str) -> None:
        self.status_label.setText(f"Download failed: {message}")
