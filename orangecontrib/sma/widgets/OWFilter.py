import numpy as np
import re

import progressmonitor
from AnyQt.QtCore import Qt
from AnyQt.QtGui import QIntValidator, QColor
from AnyQt.QtWidgets import QApplication, QCheckBox

from Orange.widgets import gui
from Orange.widgets.settings import Setting
from Orange.widgets.widget import OWWidget, Input, Output, Msg
from orangecontrib.text.corpus import Corpus
from orangecontrib.text.widgets.utils.concurrent import asynchronous
from orangecontrib.text.widgets.utils.widgets import ListEdit
from progressmonitor import ProgressMonitor

from orangecontrib.sma.index import get_index
from orangecontrib.sma.widgets.OWDictionary import Dictionary


def parse_query(string):
    m = re.match("([^#]*\w)#(.*)", string)
    l, q = m.groups() if m else [string, string]
    return l.strip(), q.strip()


QUERY_MODES = ['count', 'filter']

class OWQuerySearch(OWWidget):
    name = "Query Search"
    description = "Subset a Corpus based on a query"
    icon = "icons/queryfilter.svg"
    priority = 10

    want_main_area = False
    resizing_enabled = False

    queries = Setting('')
    dictionary_text = Setting('')
    include_unmatched = Setting(False)
    context_window = Setting('')
    dictionary_on = False
    window_disabled_text = ''

    query_mode = Setting(0)

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
        self.dictionarybox = ListEdit(self, 'dictionary_text', '', 60, self)
        self.dictionarybox.setTextColor(QColor(100, 100, 100))
        self.dictionarybox.setReadOnly(True)
        self.import_box.layout().addWidget(self.dictionarybox)

        query_box = gui.widgetBox(self.controlArea, 'Query', addSpace=True)
        self.querytextbox = ListEdit(self, 'queries', '', 80, self)
        query_box.layout().addWidget(self.querytextbox)

        query_parameter_box = gui.hBox(self.controlArea, self)
        gui.radioButtonsInBox(query_parameter_box, self, 'query_mode', btnLabels=QUERY_MODES, box="Query mode", callback=self.toggle_mode)

        self.count_mode_parameters = gui.vBox(query_parameter_box, self)
        gui.checkBox(self.count_mode_parameters, self, 'include_unmatched', label="Include unmatched documents")

        self.filter_mode_parameters = gui.widgetBox(query_parameter_box, self)
        gui.lineEdit(self.filter_mode_parameters, self, "context_window", 'Output words in context window',
                     validator=QIntValidator())

        self.toggle_mode()

        info_box = gui.hBox(self.controlArea, 'Status')
        self.status = 'Waiting for input'
        gui.label(info_box, self, '%(status)s')

        self.search_button = gui.button(self.controlArea, self, 'Search',
                                        self.start_stop,
                                        focusPolicy=Qt.NoFocus)

    def run_search(self):
        if not self.dictionary_on and not self.queries:
            self.Error.no_query()
        else:
            self.Error.no_query.clear()
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
        self.Error.no_query.clear()

    def toggle_mode(self):
        if QUERY_MODES[self.query_mode] == 'count':
            self.filter_mode_parameters.setVisible(False)
            self.count_mode_parameters.setVisible(True)
        else:
            self.filter_mode_parameters.setVisible(True)
            self.count_mode_parameters.setVisible(False)

    @asynchronous
    def search(self):
        indices = [0]
        queries = self.queries
        if self.dictionary_on and type(self.dictionary_text) is list:
            if type(queries) is list:  ## queries starts as str, but becomes list if queries are given (don't ask)
                queries = queries + self.dictionary_text
            else:
                queries = self.dictionary_text

        with ProgressMonitor().task(100, 'Starting search..') as monitor:
            monitor.add_listener(self.callback)
            index = get_index(self.corpus, monitor=monitor.submonitor(50))

            if QUERY_MODES[self.query_mode] == 'filter':
                # simple search
                query = " OR ".join('({})'.format(parse_query(q)[1]) for q in queries)
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
                    scores = np.zeros(len(sample), dtype=np.float)

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

    @search.callback(should_raise=True)
    def callback(self, monitor):
        self.progressBarSet(monitor.progress * 100)
        self.status = monitor.message

    @search.on_start
    def on_start(self):
        self.progressBarInit()

    @search.on_result
    def on_result(self, result):
        self.progressBarFinished()
        if result:
            sample, remaining = result
            self.info.setText('%d sampled instances' % len(sample))
        else:
            sample, remaning = None, None
            self.info.setText('(no input)')
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
            self.dictionary_text = []
            self.import_box.setVisible(False)

if __name__ == '__main__':
    app = QApplication([])
    widget = OWQuerySearch()
    widget.show()
    app.exec()
    widget.saveSettings()


