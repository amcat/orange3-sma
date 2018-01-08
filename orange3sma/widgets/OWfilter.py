import numpy as np
import multiprocessing
from AnyQt.QtCore import Qt
from AnyQt.QtGui import QIntValidator
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

    queries = Setting([])
    include_counts = Setting(False)
    include_unmatched = Setting(False)
    context_window = Setting('')

    procs = CPUS-2 if CPUS > 1 else 0 ## index for PROCS_OPTIONS
    limitmb = len(LIMITMB_OPTIONS) - CPUS if CPUS <= len(LIMITMB_OPTIONS) else 0

    class Inputs:
        data = Input("Corpus", Corpus)

    class Outputs:
        sample = Output("Filtered Corpus", Corpus)
        remaining = Output("Unselected Documents", Corpus)

    class Error(OWWidget.Error):
        no_query = Msg('Please provide a query.')

    def __init__(self):
        super().__init__()

        self.corpus = None
        self.index = None  # type: Index

        # GUI
        box = gui.widgetBox(self.controlArea, "Info")
        self.info = gui.widgetLabel(box, 'Connect an input corpus to start querying')

        query_box = gui.widgetBox(self.controlArea, 'Query', addSpace=True)


        query_box.layout().addWidget(ListEdit(self, 'queries', '', 80, self))

        gui.checkBox(query_box, self, 'include_counts', label="Output query counts")
        gui.checkBox(query_box, self, 'include_unmatched', label="Include unmatched documents")

        gui.lineEdit(query_box, self, "context_window", "Output words in context window",
                     validator=QIntValidator())

        perf_box = gui.widgetBox(self.controlArea, 'Indexing performance')
        gui.comboBox(perf_box, self, 'procs', items=PROCS_OPTIONS, label="Number of processors")
        gui.comboBox(perf_box, self, 'limitmb', items=LIMITMB_OPTIONS, label="Memory limit per processor")

        self.search_button = gui.button(self.controlArea, self, 'Search',
                                        self.start_stop,
                                        focusPolicy=Qt.NoFocus)

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
            query = " OR ".join('({})'.format(q) for q in self.queries)

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
            for q in self.queries:
                # todo: implement as sparse matrix!
                scores = np.zeros(len(sample), dtype=np.int)
                for i, j in self.index.search(q, frequencies=True):
                    seen.add(i)
                    scores[i] = j
                scores = scores.reshape((len(sample), 1))
                sample.extend_attributes(scores, [q])
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



