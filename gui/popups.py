from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton


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
