from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
import sys
import chess.pgn

import utils.database
import utils.position

class PositionInfoWidget(QWidget):
    def __init__(self, database: utils.database.Database, parent=None) -> None:
        super().__init__(parent)

        self.database = database
        
        self.layout = QVBoxLayout()
        
        self.position_label = QLabel("Position Info:")
        
        self.position_info = QLabel("")
        
        self.layout.addWidget(self.position_label)
        self.layout.addWidget(self.position_info)
        
        self.setLayout(self.layout)
    
    def update_position(self, game_node: chess.pgn.GameNode) -> None:
        new_position = utils.position.gamenode_position(game_node)

        last_seen = self.database.position_last_played(new_position)
        if last_seen is not None:
            self.position_info.setText(f"Position last played at {last_seen}")
        else:
            self.position_info.setText(f"Position not seen in a real game")

# Example usage:
if __name__ == "__main__":

    app = QApplication(sys.argv)
    
    widget = PositionInfoWidget(database=utils.database.Database())
    widget.show()
    
    sys.exit(app.exec())