import os
from tempfile import TemporaryDirectory

from whoosh import scoring
from whoosh.analysis.tokenizers import SpaceSeparatedTokenizer
from whoosh.index import create_in
from whoosh.fields import *
from whoosh.qparser.default import QueryParser

from typing import Iterable

class Index(object):
    """Wrapper around a whoosh index"""

    def __init__(self, corpus):
        self.tokens = corpus.tokens
        self.tempdir = TemporaryDirectory(prefix="orange3sma_index")
        schema = Schema(text=TEXT(stored=False, analyzer=SpaceSeparatedTokenizer()))
        self.index = create_in(self.tempdir.name, schema)
        w = self.index.writer()
        for doc_tokens in self.tokens:
            w.add_document(text=doc_tokens)
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
                return ((results.docnum(i), int(results.score(i))) for i in range(results.scored_length()))
            else:
                return results.docs()

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
                docnum = matcher.id()
                yield docnum, list(get_window_tokens(self.tokens[docnum], matcher.spans()))
                matcher.next()

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

    print("Documents:")
    for x in d:
        print("-", x['headline']," : ", x['text'])

    ix = Index(c)
    query = sys.argv[1]
    print("\nmatched docs:", list(ix.search(sys.argv[1])))
    print("\nwindows:")
    for i, text in ix.get_context(query, window=2):
        print(i, text)


    scores = list(ix.search(query, frequencies=True))
    print(scores)
    import numpy as np
    x = np.array([[3,4]])

    c.extend_attributes(x, "test")
    print(c)

