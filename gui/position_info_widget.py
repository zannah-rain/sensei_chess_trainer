from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLabel, QLineEdit, QPlainTextEdit
from PySide6.QtWidgets import QApplication
import sys
import chess.pgn

import utils.database


class PositionInfoWidget(QWidget):
    """
    Shows and edits everything about the currently displayed position: its name,
    manual evaluation, and free-text comment (all editable, writing straight through
    to the database), plus read-only last-seen/engine-evaluation/puzzle info.
    """

    def __init__(self, database: utils.database.Database, parent=None) -> None:
        super().__init__(parent)

        self.database = database
        self._position: str = None  # the position currently displayed; save callbacks write to this

        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._save_name)

        self.manual_eval_edit = QLineEdit()
        self.manual_eval_edit.editingFinished.connect(self._save_manual_evaluation)

        self.comment_edit = QPlainTextEdit()
        self.comment_edit.textChanged.connect(self._save_comment)

        self.last_seen_label = QLabel()
        self.stockfish_eval_label = QLabel()
        self.leela_eval_label = QLabel()
        self.puzzle_info_label = QLabel()

        form = QFormLayout()
        form.addRow("Name:", self.name_edit)
        form.addRow("Manual Eval:", self.manual_eval_edit)

        self.layout = QVBoxLayout()
        self.layout.addLayout(form)
        self.layout.addWidget(self.last_seen_label)
        self.layout.addWidget(self.stockfish_eval_label)
        self.layout.addWidget(self.leela_eval_label)
        self.layout.addWidget(self.puzzle_info_label)
        self.layout.addWidget(QLabel("Comment:"))
        self.layout.addWidget(self.comment_edit)

        self.setLayout(self.layout)

    def update_position(self,
                        position: str,
                        last_seen,
                        name: str,
                        comment: str,
                        manual_evaluation,
                        puzzle_summary: str,
                        stockfish_eval="Evaluating…",
                        leela_eval="Evaluating…") -> None:
        """
        Repopulates every field for a newly-displayed position. stockfish_eval/
        leela_eval default to a placeholder since they come from a background
        engine evaluation that hasn't necessarily finished yet - call update_evals()
        once it has.
        """
        self._position = position

        self.name_edit.blockSignals(True)
        self.name_edit.setText(name or "")
        self.name_edit.blockSignals(False)

        self.manual_eval_edit.blockSignals(True)
        self.manual_eval_edit.setText("" if manual_evaluation is None else str(manual_evaluation))
        self.manual_eval_edit.blockSignals(False)

        self.comment_edit.blockSignals(True)
        self.comment_edit.setPlainText(comment or "")
        self.comment_edit.blockSignals(False)

        if last_seen is not None:
            self.last_seen_label.setText(f"Position last played at {last_seen}")
        else:
            self.last_seen_label.setText("Position not seen in a real game")
        self.stockfish_eval_label.setText(f"Stockfish evaluation: {stockfish_eval}")
        self.leela_eval_label.setText(f"Leela evaluation: {leela_eval}")
        self.puzzle_info_label.setText(puzzle_summary)

    def update_evals(self, stockfish_eval: float, leela_eval: float) -> None:
        """Patches in the real Stockfish/Leela evaluations once the background
        evaluation that update_position() left pending has finished."""
        self.stockfish_eval_label.setText(f"Stockfish evaluation: {stockfish_eval}")
        self.leela_eval_label.setText(f"Leela evaluation: {leela_eval}")

    def _save_name(self) -> None:
        if self._position is not None:
            self.database.set_position_name(position=self._position, name=self.name_edit.text())

    def _save_manual_evaluation(self) -> None:
        if self._position is not None:
            text = self.manual_eval_edit.text()
            self.database.set_position_manual_evaluation(
                position=self._position, manual_evaluation=float(text) if text else None)

    def _save_comment(self) -> None:
        if self._position is not None:
            self.database.set_position_comment(position=self._position, comment=self.comment_edit.toPlainText())


# Example usage:
if __name__ == "__main__":

    app = QApplication(sys.argv)

    widget = PositionInfoWidget(database=utils.database.Database())
    widget.show()

    sys.exit(app.exec())
