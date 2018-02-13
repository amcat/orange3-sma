import numpy as np
from Orange.widgets.settings import Setting

from AnyQt.QtWidgets import QCheckBox

from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import OWWidget, Msg

from Orange.widgets import gui

from orangecontrib.text import Corpus


class OWPosFilter(OWWidget):
    name = "POS filter"
    description = "Filter tokens on POS tags"
    icon = "icons/filter.svg"
    priority = 10

    want_main_area = False
    resizing_enabled = True

    pos_options = []
    pos_i = []
    pos = Setting([])

    drop_tag = Setting(True)
    drop_empty_doc = Setting(True)

    class Inputs:
        in_corpus = Input("Corpus", Corpus)

    class Outputs:
        out_corpus = Output("Corpus", Corpus)

    class Error(OWWidget.Error):
        no_tokens = Msg('No tokens left')

    def __init__(self):
        super().__init__()

        self.corpus = None

        gui.listBox(self.controlArea, self, 'pos_i', labels='pos_options', box = 'POS tags', selectionMode=2)
        gui.button(self.controlArea, self, 'Drop tag', toggleButton=True, value='drop_tag', buttonType=QCheckBox)
        gui.button(self.controlArea, self, 'Drop empty documents', toggleButton=True, value='drop_empty_doc', buttonType=QCheckBox)

        self.cs = gui.label(self.controlArea, self, 'Remembered selection: %(pos)s')
        self.cs.setWordWrap(True);

        gui.button(self.controlArea, self, 'Filter', self.filter_pos)


    def progress_with_info(self, n_done, n_all):
        self.progressBarSet(100 * (n_done / n_all if n_all else 1), None)  # prevent division by 0

    def filter_pos(self):
        self.pos = [self.pos_options[i] for i in self.pos_i]
        valid_docs = []
        if self.corpus.pos_tags is not None:
            out = self.corpus.copy()
            out._tokens = self.corpus._tokens.copy()
            out.pos_tags = self.corpus.pos_tags.copy()

            self.progressBarInit(None)
            n = len(self.corpus.pos_tags)
            for i, d in enumerate(self.corpus.pos_tags):

                selected = []
                for j, p in enumerate(d):
                    if p in self.pos:
                        selected.append(j)

                if len(selected) > 0:
                    valid_docs.append(i)
                out._tokens[i] = [self.corpus._tokens[i][j] for j in selected]
                if not self.drop_tag:
                    out.pos_tags[i] = [self.corpus.pos_tags[i][j] for j in selected]
                self.progress_with_info(i, n)

            if self.drop_tag:
                out.pos_tags = None

            if self.drop_empty_doc:
                out = out[valid_docs]

            self.progressBarFinished(None)


        if len(valid_docs) == 0:
            self.Error.no_tokens()
            self.Outputs.out_corpus.send(None)
        else:
            self.Error.no_tokens.clear()
            self.Outputs.out_corpus.send(out)


    def get_pos_options(self):
        pos = set()
        if self.corpus.pos_tags is not None:
            for d in self.corpus.pos_tags:
                pos = pos.union(np.unique(d))
        self.pos_options = sorted(list(pos))
        self.pos_i = [i for i,v in enumerate(self.pos_options) if v in self.pos]
        self.cs.setVisible(len(self.pos_options) == 0)

    @Inputs.in_corpus
    def set_data(self, in_corpus):
        self.corpus = in_corpus
        if self.corpus:
            self.get_pos_options()
            self.filter_pos()
            return
        self.Outputs.out_corpus.send(None)



if __name__ == '__main__':
    None