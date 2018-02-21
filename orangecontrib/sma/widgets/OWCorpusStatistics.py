from collections import OrderedDict
from typing import Mapping


import numpy as np
from Orange.data.domain import Domain
from Orange.data.table import Table
from Orange.data.variable import StringVariable, ContinuousVariable
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import OWWidget
from Orange.widgets import gui
from orangecontrib.text.widgets.utils.concurrent import asynchronous
from progressmonitor import monitored, ProgressMonitor

from orangecontrib.text import Corpus
from orangecontrib.sma.index import get_index

def _create_table(words, scores: Mapping[str, np.array]) -> Table:
    """
    Create an Orange table from the word scores
    :param words: list of words
    :param scores: mapping of {label: score_array}. Use ordereddict to preserve column order
    :return: a Table object
    """
    values = list(scores.values())
    order = (-values[0]).argsort()
    data = np.column_stack(values)[order]
    words = np.array(words).reshape(len(words), 1)[order]
    domain = Domain([ContinuousVariable(label) for label in scores],
                    metas=[StringVariable("term")])
    return Table(domain, data, metas=words)


@monitored(100)
def compare(corpus: Corpus, reference_corpus: Corpus, monitor: ProgressMonitor):
    index = get_index(corpus, monitor=monitor.submonitor(33))
    ref_index = get_index(reference_corpus, monitor=monitor.submonitor(33))

    with index.reader() as r, ref_index.reader() as r2:
        words = list(set(r.field_terms("text")) | set(r2.field_terms("text")))
        n = len(words)
        N = len(list(r.all_doc_ids()))  # TODO more efficient way?
        counts, docfreqs, refcounts, refdocfreqs = [np.empty(n) for _ in range(4)]
        for i, word in enumerate(words):
            counts[i] = r.frequency('text', word)
            docfreqs[i] = r.doc_frequency('text', word)
            refcounts[i] = r2.frequency('text', word)
            refdocfreqs[i] = r2.doc_frequency('text', word)
    monitor.update(20)

    def relfreq(c):
        c2 = c+1
        return c2/c2.sum()

    relc, relcr = relfreq(counts), relfreq(refcounts)
    over = relc / relcr
    return _create_table(words, OrderedDict([
            ("overrepresentation", over),
            ("percent", relc),
            ("frequency", counts),
            ("docfreq", docfreqs),
            ("ref_percent", relcr),
            ("ref_frequency", refcounts),
            ("ref_docfreq", refdocfreqs),
       ]))


@monitored(100)
def frequencies(corpus, monitor):
    index = get_index(corpus, monitor.submonitor(50))

    for i in range(25):
        monitor.update()
        import time; time.sleep(.1)

    with index.reader() as r:
        words = list(r.field_terms("text"))
        n = len(words)
        N = len(list(r.all_doc_ids()))  # TODO more efficient way?
        counts, docfreqs, reldocfreqs = [np.empty(n) for _ in range(3)]
        for i, word in enumerate(words):
            counts[i] = r.frequency('text', word)
            docfreqs[i] = r.doc_frequency('text', word)
            reldocfreqs[i] = docfreqs[i] / N
    monitor.update(10)
    return _create_table(words, OrderedDict([
        ("frequency", counts),
        ("docfreq", docfreqs),
        ("relative_docfreq", reldocfreqs),
    ]))


class OWCorpusStatistics(OWWidget):
    name = "Corpus Statistics"
    description = "Calculate word frequencies and optionally compare to reference corpus"
    icon = "icons/stats.svg"
    priority = 10

    want_main_area = False
    resizing_enabled = False

    class Inputs:
        data = Input("Corpus", Corpus)
        reference = Input("Reference Corpus", Corpus)

    class Outputs:
        statistics = Output("Statistics", Table)

    class Error(OWWidget.Error):
        pass

    def __init__(self):
        super().__init__()

        self.corpus = None
        self.reference_corpus = None

        box = gui.widgetBox(self.controlArea, "Info")
        self.info = gui.widgetLabel(box, 'Output to Data Table widget to view results')

    @asynchronous
    def calculate(self):
        with ProgressMonitor().task(100, 'Calculating statistics..') as monitor:
            monitor.add_listener(self.callback)
            if self.reference_corpus:
                t = compare(self.corpus, self.reference_corpus, monitor=monitor)
            else:
                t = frequencies(self.corpus, monitor=monitor)
            return t

    @calculate.on_result
    def on_result(self, result):
        self.progressBarFinished()
        self.Outputs.statistics.send(result)

    def callback(self, monitor):
        self.progressBarSet(monitor.progress * 100)

    def on_start(self):
        self.progressBarInit()

    def go(self):
        if self.corpus is None:
            self.Outputs.statistics.send(None)
        else:
            self.calculate()

    @Inputs.data
    def set_data(self, corpus):
        self.corpus = corpus
        self.go()

    @Inputs.reference
    def set_refdata(self, reference_corpus):
        self.reference_corpus = reference_corpus
        self.go()


if __name__ == '__main__':
    from Orange import data
    from orangecontrib.text.corpus import Corpus

    def corpus(*texts):
        metas = [(data.StringVariable('text'), lambda doc: doc['text'])]
        d = [{'text': t} for t in texts]
        c = Corpus.from_documents(d, 'example', [], [], metas, [-1])
        c.set_text_features([metas[0][0]])
        return c
    c1 = corpus("dit is een test", "met een document")
    c2 = corpus("test", "en nog een document")
    print(compare(c1, c2))
