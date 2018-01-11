import numpy as np
import multiprocessing
import re
from AnyQt.QtCore import Qt
from AnyQt.QtGui import QIntValidator, QColor
from AnyQt.QtWidgets import QApplication, QCheckBox

from Orange.widgets import gui
from Orange.widgets.settings import Setting
from Orange.widgets.widget import OWWidget, Input, Output, Msg
from orangecontrib.text.corpus import Corpus
from orangecontrib.text.widgets.utils.concurrent import asynchronous
from orangecontrib.text.widgets.utils.decorators import gui_require
from orangecontrib.text.widgets.utils.widgets import ListEdit

from orange3sma.index import get_index
from orange3sma.progress import progress_monitor
from orange3sma.widgets.OWDictionary import Dictionary


def parse_query(string):
    m = re.match("([^#]*\w)#(.*)", string)
    l, q = m.groups() if m else [string, string]
    return l.strip(), q.strip()


class OWQueryFilter(OWWidget):
    name = "Query Filter"
    description = "Subset a Corpus based on a query"
    icon = "icons/DataSamplerA.svg"
    priority = 10

    want_main_area = False
    resizing_enabled = False

    queries = Setting('')
    dictionary_text = Setting('')
    include_counts = Setting(False)
    include_unmatched = Setting(False)
    context_window = Setting('')
    dictionary_on = True

    class Inputs:
        data = Input("Corpus", Corpus)
        dictionary = Input("Dictionary", Dictionary)

    class Outputs:
        sample = Output("Filtered Corpus", Corpus)
        remaining = Output("Unselected Documents", Corpus)

    class Error(OWWidget.Error):
        no_query = Msg('Please provide a query.')

    def __init__(self):
        super().__init__()

        self.corpus = None

        # GUI
        box = gui.widgetBox(self.controlArea, "Info")
        self.info = gui.widgetLabel(box, 'Connect an input corpus to start querying')

        self.import_box = gui.vBox(self.controlArea, 'Dictionary')
        self.import_box.setVisible(False)
        gui.button(self.import_box, self, 'Use dictionary', toggleButton=True, value='dictionary_on', buttonType=QCheckBox)
        self.dictionarybox = ListEdit(self, 'queries', '', 60, self)
        self.dictionarybox.setTextColor(QColor(100, 100, 100))
        self.dictionarybox.setReadOnly(True)
        self.import_box.layout().addWidget(self.dictionarybox)
        
        query_box = gui.widgetBox(self.controlArea, 'Query', addSpace=True)
        self.querytextbox = ListEdit(self, 'queries', '', 80, self)
        query_box.layout().addWidget(self.querytextbox)
       
        gui.checkBox(query_box, self, 'include_counts', label="Output query counts")
        gui.checkBox(query_box, self, 'include_unmatched', label="Include unmatched documents")

        gui.lineEdit(query_box, self, "context_window", "Output words in context window",
                     validator=QIntValidator())

        info_box = gui.hBox(self.controlArea, 'Status')
        self.status = 'Waiting for input'
        gui.label(info_box, self, '%(status)s')

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
        
    def import_dictionary(self):    
        self.dictionary_text = []   
        for label, query in self.dictionary:
            q = label.strip() + '# ' + query.strip() if label else query.strip()
            self.dictionary_text.append(q)
        self.dictionarybox.setText('\n'.join(self.dictionary_text))
    
    @asynchronous
    def search(self):
        indices = [0]
        queries = self.dictionary_text + self.queries if self.dictionary_on else self.queries

        with progress_monitor(self, 'status').task(100) as monitor:
            index = get_index(self.corpus, monitor=monitor.submonitor(50))

            if not self.include_counts:
                # simple search
                query = " OR ".join('({})'.format(q) for q in queries)

                if not self.context_window:
                    selected = list(index.search(query))
                    sample = self.corpus[selected]
                else:
                    sample = self.corpus.copy()
                    sample._tokens = sample._tokens.copy()
                    selected = []
                    for i, context in index.get_context(query, int(self.context_window)):
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
                for q in queries:
                    label, q = parse_query(q)

                    # todo: implement as sparse matrix!
                    scores = np.zeros(len(sample), dtype=np.int)
                    for i, j in index.search(q, frequencies=True):
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
        self.run_search()

    @Inputs.dictionary
    def set_dictionary(self, dictionary):
        if dictionary:
            self.dictionary_on = True
            self.import_box.setVisible(True)
            self.dictionary = dictionary.get_dictionary()
            self.import_dictionary()
        else:
            self.dictionary_on = False
            self.import_box.setVisible(False)
            
if __name__ == '__main__':
    app = QApplication([])
    widget = OWQueryFilter()
    widget.show()
    app.exec()
    widget.saveSettings()


