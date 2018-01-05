import sys
import numpy

import Orange.data
from Orange.widgets.widget import OWWidget, Input, Output
from Orange.widgets import gui

from Orange import data
from orangecontrib.text.corpus import Corpus

class OWQueryFilter(OWWidget):
    name = "Query Filter"
    description = "Subset a Corpus based on a query"
    icon = "icons/DataSamplerA.svg"
    priority = 10

    class Inputs:
        #data = Input("Data", Orange.data.Table)
        data = Input("Corpus", Corpus)

    class Outputs:
        #sample = Output("Sampled Data", Orange.data.Table)
        corpus = Output("Corpus", Corpus)

    want_main_area = False

    def __init__(self):
        super().__init__()

        # GUI
        box = gui.widgetBox(self.controlArea, "Info")
        self.infoa = gui.widgetLabel(box, 'No data on input yet, waiting to get something.')
        self.infob = gui.widgetLabel(box, '')

    @Inputs.data
    def set_data(self, corpus):
        if corpus is not None:
            self.infoa.setText('%d instances in input data set' % len(dataset))
            indices = [0]
            sample = corpus[indices]
            self.infob.setText('%d sampled instances' % len(sample))
            self.Outputs.sample.send(sample)
        else:
            self.infoa.setText('No data on input yet, waiting to get something.')
            self.infob.setText('')
            self.Outputs.sample.send("Sampled Data")


