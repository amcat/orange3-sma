import logging
import os
from tempfile import TemporaryDirectory
from threading import Semaphore, Lock

from progressmonitor import monitored, ProgressMonitor
from whoosh import scoring
from whoosh.analysis.tokenizers import SpaceSeparatedTokenizer
from whoosh.index import create_in
from whoosh.fields import *
from whoosh.qparser.default import QueryParser
from orangecontrib.text.corpus import Corpus

from typing import Iterable

_GLOBAL_LOCK = Lock()

class Index(object):
    """Wrapper around a whoosh index"""

    def __init__(self, corpus, procs=2, limitmb=256):
        self.tokens = corpus.tokens
        self.tempdir = TemporaryDirectory(prefix="orange3sma_index")
        schema = Schema(text=TEXT(stored=False, analyzer=SpaceSeparatedTokenizer()), doc_i=NUMERIC(int, 64, signed=False, stored=True))
        self.index = create_in(self.tempdir.name, schema)
        w = self.index.writer(limitmb=limitmb, procs=procs, multisegment=True) 
        for doc_i, doc_tokens in enumerate(self.tokens):
            w.add_document(text=doc_tokens, doc_i=doc_i)
        w.commit()
        
    def search(self, query: str, frequencies=False):
        """
        Get the indices of the documents matching the query
        :param query: The whoosh query string
        :param frequencies: If true, return pairs of (docnum, frequency) rather than only docnum
        :return: sequence of document numbers (and freqs, if frequencies is True)
        """
        query = QueryParser("text", self.index.schema).parse(query)
        with self.index.searcher(weighting=scoring.Frequency) as searcher:
            results = searcher.search(query, limit=None, scored=frequencies, sortedby=None)

            if frequencies:                
                return [(results[i]['doc_i'], int(results.score(i))) for i in range(results.scored_length())]
            else:
                return [results[i]['doc_i'] for i in range(len(results))]

    def get_context(self, query: str, window: int = 30):
        """
        Get the words in the context (n-word window) of all locations of the string

        :param query: search query
        :param window: window size (in words)
        :return: a generator of (id, text) pairs
        """
        def get_window_tokens(tokens, spans):
            position = -1
            for span in spans:
                for position in range(max(position + 1, span.start - window), min(len(tokens), span.end + window + 1)):
                    yield tokens[position]

        query = QueryParser("text", self.index.schema).parse(query)
        with self.index.searcher() as searcher:
            matcher = query.matcher(searcher)
            while matcher.is_active():
                docnum = searcher.reader().stored_fields(matcher.id())['doc_i']
                yield docnum, list(get_window_tokens(self.tokens[docnum], matcher.spans()))
                matcher.next()

    def term_statistics(self):
        """
        Yield the term and document frequency for each term in the index
        :return: generator of (term, termfreq, docfreq) triples
        """
        with self.index.reader() as r:
            for t in r.field_terms('text'):
                yield t, r.doc_frequency('text', t), r.frequency('text', t)

    def reader(self, *args, **kargs):
        return self.index.reader(*args, **kargs)


@monitored(100)
def get_index(corpus: Corpus, monitor: ProgressMonitor) -> Index:
    """
    Get the index for the provided corpus, reindexing (and tokenizing) if needed
    """
    with _GLOBAL_LOCK:
        if not hasattr(corpus, "_orange3sma_index_lock"):
            corpus._orange3sma_index_lock = Lock()
    with corpus._orange3sma_index_lock:
        ix = getattr(corpus, "_orange3sma_index", None)
        if not (ix and ix.tokens is corpus._tokens):
            corpus.tokens  # force tokens
            monitor.update(50)
            logging.info("(re-)indexing corpus")
            ix = Index(corpus)
            corpus._orange3sma_index = ix
    return ix

if __name__ == '__main__':
    import sys
    from Orange import data
    from orangecontrib.text.corpus import Corpus

    metas = [(data.StringVariable('headline'), lambda doc: doc['headline']),
             (data.StringVariable('text'), lambda doc: doc['text']),
             (data.StringVariable('id'), lambda doc: doc['id'])]
    text_features = [metas[0][0], metas[1][0]]
    title_indices = [-1]
    d = [{'headline': 'titel_a', 'text': 'x x y this tests a test y x x', 'id': '1'},
         {'headline': 'titel_b', 'text': 'more tests!!!', 'id': '2'}]
    c = Corpus.from_documents(d, 'example', [], [], metas, title_indices)
    c.set_text_features(text_features)

    _ix = Index(c)

    import numpy as np
    terms = list(_ix.term_statistics())
    words = np.array([["a"], ["b"]])
    print(words)

