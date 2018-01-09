import numpy as np
import multiprocessing
from AnyQt.QtWidgets import QApplication, QGridLayout, QLabel, QLineEdit, QSizePolicy, QScrollArea
from AnyQt.QtCore import QSize, Qt
from AnyQt.QtGui import QIntValidator
import Orange
from Orange.widgets import gui
from Orange.widgets.settings import Setting
from Orange.widgets.widget import OWWidget, Input, Output, Msg
from orangecontrib.text.corpus import Corpus
from orangecontrib.text.widgets.utils.concurrent import asynchronous
from orangecontrib.text.widgets.utils.decorators import gui_require
from orangecontrib.text.widgets.utils.widgets import ListEdit

from orange3sma.index import Index

class OWDictionary(OWWidget):
    name = "Dictionary"
    description = "Create a dictionary"
    icon = "icons/dictionary.svg"
    priority = 10

    want_main_area = False
    resizing_enabled = True
    
    queries = Setting([["", ""], ["", ""]])
    querytable = None
    querytable_attr = []
    querytable_metas = []
    querytable_vars = []
    label_in = [None]
    query_in = [None]

    class Inputs:
        data = Input("Table", Orange.data.Table)

    class Outputs:
        dictionary = Output("Dictionary", Orange.data.Table)

    class Error(OWWidget.Error):
        no_query = Msg('Please provide a query.')

    def __init__(self):
        super().__init__()

        self.query_edits = []
        self.remove_buttons = []
        
        # GUI
        scrollArea = QScrollArea()
       

        #### header
        head_box = gui.hBox(self.controlArea)
        head_box.setMaximumHeight(150)
        
        info_box = gui.widgetBox(head_box, 'Info')
        self.info = gui.widgetLabel(info_box, 'Import and/or create query dictionary')

        ## from input
        input_box = gui.widgetBox(head_box, "Import")
        input_box.setMaximumWidth(350)
        inputline_box = gui.hBox(input_box)
        gui.listBox(inputline_box, self, 'label_in', labels='querytable_vars', box = 'label column')
        gui.listBox(inputline_box, self, 'query_in', labels='querytable_vars', box = 'query column')
        gui.button(input_box, self, 'Import', self.queries_from_table)

        ## query field
        query_box = gui.widgetBox(self.controlArea)
        
        self.queries_box = QGridLayout()
        query_box.layout().addLayout(self.queries_box)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(query_box)

        querygridbox = gui.widgetBox(self.controlArea, 'Query')
        querygridbox.layout().addWidget(scroll)       
        
        querygridbox.setMinimumHeight(200)
        querygridbox.setMaximumHeight(400)
        querygridbox.setMinimumWidth(500)
        gui.rubber(query_box)

        self.queries_box.setColumnMinimumWidth(0, 5)
        self.queries_box.setColumnMinimumWidth(1, 60)
        self.queries_box.setColumnMinimumWidth(2, 350)
        self.queries_box.setColumnStretch(0, 0)
        self.queries_box.setColumnStretch(1, 0)
        self.queries_box.setColumnStretch(2, 100)
        self.queries_box.addWidget(QLabel("Label"), 0, 1)
        self.queries_box.addWidget(QLabel("Query"), 0, 2)
        self.update_queries()

        gui.button(querygridbox, self, "add query", callback=self.add_row,autoDefault=False)

        ## buttons
        scarybuttonbox = gui.hBox(self.controlArea)
        scarybuttonbox.layout().setAlignment(Qt.AlignRight)
        gui.button(scarybuttonbox, self, "remove all queries", callback=self.remove_all, width=150)

        gui.button(self.controlArea, self, 'Send queries', self.send_queries)

    def send_queries(self):
        self.queries = [[label.text(), query.text()] for label, query in self.query_edits if not query.text() == '']
        self.update_queries()
        domain = Orange.data.Domain([], metas = [
                                     Orange.data.StringVariable("label"),
                                     Orange.data.StringVariable("query")])

        out = Orange.data.Table(domain, self.queries)
        self.Outputs.dictionary.send(out)


    def adjust_n_query_rows(self):
        def _add_line():
            self.query_edits.append([])
            n_lines = len(self.query_edits)

            label_edit = QLineEdit()
            self.query_edits[-1].append(label_edit)
            self.queries_box.addWidget(label_edit, n_lines, 1)

            query_edit = QLineEdit()
            self.query_edits[-1].append(query_edit)
            self.queries_box.addWidget(query_edit, n_lines, 2)

            button = gui.button(
                None, self, label='×', flat=True, height=20,
                styleSheet='* {font-size: 16pt; color: silver}'
                           '*:hover {color: black}',
                autoDefault=False, callback=self.remove_row)
            button.setMinimumSize(QSize(3, 3))
            self.remove_buttons.append(button)
            self.queries_box.addWidget(button, n_lines, 0)
            for coli, kwargs in enumerate(
                    (dict(alignment=Qt.AlignRight),
                     dict(alignment=Qt.AlignLeft, styleSheet="color: gray"))):
                label = QLabel(**kwargs)
                self.queries_box.addWidget(label, n_lines, 3 + coli)

        def _remove_line():
            for edit in self.query_edits.pop():
                edit.deleteLater()
            self.remove_buttons.pop().deleteLater()

        n = len(self.queries)
        while n > len(self.query_edits):
            _add_line()
        while len(self.query_edits) > n:
            _remove_line()

    def add_row(self):
        self.queries.append(["", ""])
        self.adjust_n_query_rows()

    def remove_row(self):
        remove_idx = self.remove_buttons.index(self.sender())
        del self.queries[remove_idx]
        self.update_queries()

    def remove_all(self):
        self.queries = []
        self.update_queries()
       
    def update_queries(self):
        self.adjust_n_query_rows()
        self.queries_to_edits()

    def queries_to_edits(self):
        for editr, textr in zip(self.query_edits, self.queries):
            for edit, text in zip(editr, textr):
                edit.setText(text)

    def table_to_dict(self, table):
        d = {}
        attr =  [x.name for x in table.domain.attributes]
        metas = [x.name for x in table.domain.metas]
        for i, a in enumerate(attr):
           d[a] = table.attributes


    def get_column(self, table, name):
        for i, a in enumerate(self.querytable_attr):
            if a == name:   
                return [str(v[0]) for v in table[:,i]]  ## orange.table doesn't return single list, like numpy
        for i, m in enumerate(self.querytable_metas):
            if m == name:
                return [str(v[0]) for v in table.metas[:,i]]

    def queries_from_table(self):
        label_in = self.label_in[0]
        query_in = self.query_in[0]
        if self.querytable is not None and label_in is not None and query_in is not None:
            label = self.get_column(self.querytable, self.querytable_vars[label_in])
            query = self.get_column(self.querytable, self.querytable_vars[query_in])
            add_queries = [list(a) for a in zip(label,query)]
            self.queries = self.queries + add_queries
            self.update_queries()

    @Inputs.data
    def set_data(self, data):
        if data is not None:
            self.querytable = data
            self.querytable_attr = [x.name for x in data.domain.attributes]
            self.querytable_metas = [x.name for x in data.domain.metas]
            self.querytable_vars = self.querytable_attr + self.querytable_metas
        else:
            self.querytable = None
            self.querytable_attr, self.querytable_metas, self.querytable_vars = [], [], []
            self.label_in, self.query_in = [None], [None]


if __name__ == '__main__':
    app = QApplication([])
    widget = OWDictionary()
    widget.show()
    app.exec()
    widget.saveSettings()
