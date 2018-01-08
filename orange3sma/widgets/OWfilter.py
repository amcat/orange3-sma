import numpy as np
import multiprocessing
from AnyQt.QtWidgets import QApplication, QGridLayout, QLabel, QLineEdit, QSizePolicy, QScrollArea
from AnyQt.QtCore import QSize, Qt
from AnyQt.QtGui import QIntValidator
from Orange.data import Table
from Orange.widgets import gui
from Orange.widgets.settings import Setting
from Orange.widgets.widget import OWWidget, Input, Output, Msg
from orangecontrib.text.corpus import Corpus
from orangecontrib.text.widgets.utils.concurrent import asynchronous
from orangecontrib.text.widgets.utils.decorators import gui_require
from orangecontrib.text.widgets.utils.widgets import ListEdit

from orange3sma.index import Index

CPUS = multiprocessing.cpu_count()
PROCS_OPTIONS = list(range(1,CPUS+1))
LIMITMB_OPTIONS = [128,256,512,1024]

class OWQueryFilter(OWWidget):
    name = "Query Filter"
    description = "Subset a Corpus based on a query"
    icon = "icons/DataSamplerA.svg"
    priority = 10

    want_main_area = False
    resizing_enabled = False

    #queries = Setting([])
    include_counts = Setting(False)
    include_unmatched = Setting(False)
    context_window = Setting('')

    queries = Setting([["", ""], ["", ""]])
    procs = CPUS-2 if CPUS > 1 else 0 ## index for PROCS_OPTIONS
    limitmb = len(LIMITMB_OPTIONS) - CPUS if CPUS <= len(LIMITMB_OPTIONS) else 0

    class Inputs:
        data = Input("Corpus", Corpus)
        #dictionary = Input("Table", Table)

    class Outputs:
        sample = Output("Filtered Corpus", Corpus)
        remaining = Output("Unselected Documents", Corpus)

    class Error(OWWidget.Error):
        no_query = Msg('Please provide a query.')

    def __init__(self):
        super().__init__()

        self.corpus = None
        self.index = None  # type: Index

        self.query_edits = []
        self.remove_buttons = []
        self.counts = []
    
        # GUI
        head_box = gui.widgetBox(self.controlArea, "Info")
        self.info = gui.widgetLabel(head_box, 'Connect an input corpus to start querying')

        query_box = gui.widgetBox(self.controlArea, 'Query', addSpace=True, stretch=100)
        #patternbox = gui.vBox(query_box, box=True, addSpace=True)
        self.queries_box = queries_box = QGridLayout()
        query_box.layout().addLayout(self.queries_box)
        box = gui.hBox(query_box)
        gui.button(
            box, self, "+ query row", callback=self.add_row, autoDefault=False, flat=True,
            minimumSize=(QSize(5, 20)))
        gui.rubber(box)
        self.queries_box.setColumnMinimumWidth(0, 5)
        self.queries_box.setColumnMinimumWidth(2, 250)
        self.queries_box.setColumnStretch(1, 1)
        self.queries_box.setColumnStretch(2, 1)
        queries_box.addWidget(QLabel("Label"), 0, 1)
        queries_box.addWidget(QLabel("Query"), 0, 2)
        self.update_queries()

        gui.checkBox(query_box, self, 'include_counts', label="Output query counts")
        gui.checkBox(query_box, self, 'include_unmatched', label="Include unmatched documents")

        gui.lineEdit(query_box, self, "context_window", "Output words in context window",
                     validator=QIntValidator())

        perf_box = gui.widgetBox(self.controlArea, 'Performance ')
        gui.comboBox(perf_box, self, 'procs', items=PROCS_OPTIONS, label="Number of processors")
        gui.comboBox(perf_box, self, 'limitmb', items=LIMITMB_OPTIONS, label="Memory limit per processor")

        self.search_button = gui.button(self.controlArea, self, 'Search',
                                        self.start_stop,
                                        focusPolicy=Qt.NoFocus)


    def adjust_n_query_rows(self):
        def _add_line():
            self.query_edits.append([])
            n_lines = len(self.query_edits)
            for coli in range(1, 3):
                edit = QLineEdit()
                self.query_edits[-1].append(edit)
                self.queries_box.addWidget(edit, n_lines, coli)
            button = gui.button(
                None, self, label='×', flat=True, height=20,
                styleSheet='* {font-size: 16pt; color: silver}'
                           '*:hover {color: black}',
                autoDefault=False, callback=self.remove_row)
            button.setMinimumSize(QSize(3, 3))
            self.remove_buttons.append(button)
            self.queries_box.addWidget(button, n_lines, 0)
            self.counts.append([])
            for coli, kwargs in enumerate(
                    (dict(alignment=Qt.AlignRight),
                     dict(alignment=Qt.AlignLeft, styleSheet="color: gray"))):
                label = QLabel(**kwargs)
                self.counts[-1].append(label)
                self.queries_box.addWidget(label, n_lines, 3 + coli)

        def _remove_line():
            for edit in self.query_edits.pop():
                edit.deleteLater()
            self.remove_buttons.pop().deleteLater()
            for label in self.counts.pop():
                label.deleteLater()

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
        self.update_queries(set_queries=False)
       
    def update_queries(self, set_queries=True):
        self.adjust_n_query_rows()
        if set_queries:
            self.queries_to_edits()

    def queries_to_edits(self):
        for editr, textr in zip(self.query_edits, self.queries):
            for edit, text in zip(editr, textr):
                edit.setText(text)

    @gui_require('queries', 'no_query')
    def run_search(self):
        if self.corpus is None:
            self.info.setText('Connect an input corpus to start querying')
            self.Outputs.sample.send(None)
        else:
            # start async search
            self.search()

    def start_stop(self):
        if self.search.running:
            self.search.stop()
        else:
            self.run_search()

    @asynchronous
    def search(self):
        indices = [0]
        self.progressBarInit()

        if self.index is None:
            procs = PROCS_OPTIONS[self.procs]
            limitmb = LIMITMB_OPTIONS[self.limitmb]
            self.index = Index(self.corpus, self.procs, limitmb)
        self.progressBarAdvance(50)

        if not self.include_counts:
            # simple search
            query = " OR ".join('({})'.format(q.text()) for label, q in self.queries)

            if not self.context_window:
                selected = list(self.index.search(query))
                sample = self.corpus[selected]
            else:
                sample = self.corpus.copy()
                sample._tokens = sample._tokens.copy()
                selected = []
                for i, context in self.index.get_context(query, int(self.context_window)):
                    sample._tokens[i] = context
                    selected.append(i)
                sample = sample[selected]

            o = np.ones(len(self.corpus))
            o[selected] = 0
            remaining = np.nonzero(o)[0]
            remaining = self.corpus[remaining]
        else:
            sample = self.corpus.copy()
            remaining = None
            seen = set()
            for label, q in self.query_edits:
                label = label.text()
                q = q.text()
               
                # todo: implement as sparse matrix!
                scores = np.zeros(len(sample), dtype=np.int)
                for i, j in self.index.search(q, frequencies=True):
                    seen.add(i)
                    scores[i] = j
                scores = scores.reshape((len(sample), 1))
                sample.extend_attributes(scores, [label])
            if self.include_unmatched:
                remaining = None
            else:
                selected = list(seen)
                o = np.ones(len(self.corpus))
                o[selected] = 0
                remaining = np.nonzero(o)[0]
                remaining = self.corpus[remaining]
                sample = sample[selected]
        self.progressBarFinished()
        return sample, remaining

    @search.on_result
    def on_result(self, result):
        sample, remaining = result
        self.info.setText('%d sampled instances' % len(result))
        self.Outputs.sample.send(sample)
        self.Outputs.remaining.send(remaining)

    @Inputs.data
    def set_data(self, corpus):
        self.corpus = corpus
        self.index = None
        self.run_search()


if __name__ == '__main__':
    app = QApplication([])
    widget = OWQueryFilter()
    widget.show()
    app.exec()
    widget.saveSettings()
