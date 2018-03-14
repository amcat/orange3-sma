from collections import OrderedDict
from typing import Mapping, Tuple

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
def get_counts(corpus: Corpus, monitor: ProgressMonitor) -> Tuple[Mapping[str, int], Mapping[str, int]]:
    monitor.update(0, "Getting tokens")
    tokens = corpus.tokens  # forces tokens to be created
    n = len(tokens)
    tf, df = {}, {}  # tf: {word : freq}, df: {word: {doc_i, ...}}
    monitor.update(50, "Counting words")
    with monitor.subtask(50) as sm:
        sm.begin(n)
        for i, doc_tokens in enumerate(tokens):
            sm.update(message="Counting words {i}/{n}".format(**locals()))
            for t in doc_tokens:
                df.setdefault(t, set()).add(i)
                tf[t] = tf.get(t, 0) + 1
        df = {w: len(df[w]) for w in df}
        return tf, df


def _relfreq(c):
    c2 = c+1
    return c2/c2.sum()


@monitored(100)
def compare(corpus: Corpus, reference_corpus: Corpus, monitor: ProgressMonitor):
    tf1, df1 = get_counts(corpus, monitor.submonitor(40))
    tf2, df2 = get_counts(reference_corpus, monitor.submonitor(40))

    words = list(set(df1.keys()) | set(df2.keys()))
    counts = np.fromiter((tf1.get(t, 0) for t in words), int)
    docfreqs = np.fromiter((df1.get(t, 0) for t in words), int)
    refcounts = np.fromiter((tf2.get(t, 0) for t in words), int)
    refdocfreqs = np.fromiter((df2.get(t, 0) for t in words), int)

    relc, relcr = _relfreq(counts), _relfreq(refcounts)
    over = relc / relcr
    return _create_table(words, OrderedDict([
            ("percent", relc),
            ("frequency", counts),
            ("docfreq", docfreqs),
            ("overrepresentation", over),
            ("reference_percent", relcr),
            ("reference_frequency", refcounts),
            ("reference_docfreq", refdocfreqs),
       ]))


@monitored(100)
def frequencies(corpus, monitor):
    tf, df = get_counts(corpus, monitor.submonitor(90))

    words = list(tf.keys())
    counts = np.fromiter((tf.get(t, 0) for t in words), int)
    docfreqs = np.fromiter((df.get(t, 0) for t in words), int)
    reldocfreqs = _relfreq(counts)

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

    @calculate.callback(should_raise=True)
    def callback(self, monitor):
        self.progressBarSet(monitor.progress * 100)

    @calculate.callback(should_raise=True)
    def progress_with_info(self, n, total):
        self.output_info = '{n}/{total}'.format(**locals())
        self.progressBarSet(100 * (n / total if total else 1), None)  # prevent division by 0

    @calculate.on_start
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
