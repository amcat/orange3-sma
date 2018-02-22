import re

from AnyQt.QtWidgets import QApplication, QGridLayout, QLabel, QLineEdit, QSizePolicy, QScrollArea, QCheckBox
from AnyQt.QtCore import Qt, QTimer, QSize
import Orange
from Orange.widgets import gui
from Orange.widgets.settings import Setting
from Orange.widgets.widget import OWWidget, Input, Output, Msg

class OWDictionary(OWWidget):
    name = "Dictionary"
    description = "Create a dictionary"
    icon = "icons/dictionary.svg"
    priority = 10

    want_main_area = False
    resizing_enabled = True
    
    queries = Setting([["", ""], ["", ""]])
    querytable = None
    querytable_attr = []
    querytable_metas = []
    querytable_vars = []
    querytable_vars2 = []
    label_in = [None]
    query_in = [None]
    weight_in = [None]
    add_quotes = Setting(True)
    sync = Setting(False)
    send = Setting(False)


    class Inputs:
        data = Input("Table", Orange.data.Table)

    class Outputs:
        dictionary = Output("Dictionary", Orange.data.Table)

    class Error(OWWidget.Error):
        no_query = Msg('You need to select a query column to import, select or sync a dictionary.')

    def __init__(self):
        super().__init__()

        self.query_edits = []
        self.remove_buttons = []
        
        # GUI
        scrollArea = QScrollArea()
       

        #### header
        head_box = gui.hBox(self.controlArea)
        head_box.setMaximumHeight(200)
        
        info_box = gui.widgetBox(head_box, 'Info')
        self.info = gui.widgetLabel(info_box,
           ("Import and/or create queries\n\n" +
            "If a Table with a dictionary is connected as input,\n" +
            "it can be imported, in which case multiple query\n" +
            "terms with the same label will be combined.\n\n" +
            "If the label is a number, or if negative weights are\n" +
            "used (e.g. sentiment dictionaries), the query will be\n" +
            "split into positive and negative parts.\n\n"
            "If a row in the dictionary contains multiple terms\n" +
            "separated with spaces, it will be seen as a phrase\n" +
            "(by adding quotes). This can be turned of in case\n" +
            "rows are already boolean queries."))

        ## from input
        input_box = gui.widgetBox(head_box, "Create queries from dictionary file")
        input_box.setMaximumWidth(350)

        gui.button(input_box, self, 'multiple words are phrases', toggleButton=True, value='add_quotes',
                   buttonType=QCheckBox)
        inputline_box = gui.hBox(input_box)
        inputline_box.setMinimumHeight(70)
        gui.listBox(inputline_box, self, 'query_in', labels='querytable_vars', box = 'Query column', callback=self.update_if_sync)
        gui.listBox(inputline_box, self, 'label_in', labels='querytable_vars2', box = 'Label column', callback=self.update_if_sync)
        self.weight_select = gui.listBox(inputline_box, self, 'weight_in', labels='querytable_vars2', box = 'Weight column', callback=self.update_if_sync)

        input_button_box = gui.hBox(input_box)
        gui.button(input_button_box, self, 'Keep synchronized', self.sync_on_off, toggleButton=True, value='sync', buttonType=QCheckBox)
        gui.button(input_button_box, self, 'Import', self.import_queries)
        gui.button(input_button_box, self, 'Append', self.append_queries)

        ## query field
        query_box = gui.widgetBox(self.controlArea)
        
        self.queries_box = QGridLayout()
        query_box.layout().addLayout(self.queries_box)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(query_box)

        querygridbox = gui.widgetBox(self.controlArea, 'Query')
        querygridbox.layout().addWidget(scroll)       
        
        querygridbox.setMinimumHeight(200)
        querygridbox.setMinimumWidth(500)
        gui.rubber(query_box)

        self.queries_box.setColumnMinimumWidth(0, 5)
        self.queries_box.setColumnMinimumWidth(1, 60)
        self.queries_box.setColumnMinimumWidth(2, 350)
        self.queries_box.setColumnStretch(1, 0)
        self.queries_box.setColumnStretch(2, 100)
        self.queries_box.addWidget(QLabel("Label"), 0, 1)
        self.queries_box.addWidget(QLabel("Query"), 0, 2)
        self.update_queries()

        gui.button(query_box, self, "add query", callback=self.add_row, autoDefault=False)

        ## buttons
        scarybuttonbox = gui.hBox(self.controlArea)
        scarybuttonbox.layout().setAlignment(Qt.AlignRight)
        gui.button(scarybuttonbox, self, "remove all queries", callback=self.remove_all, width=150)

        QTimer.singleShot(0, self.send_queries) ## for send on startup

    def update_if_sync(self):
        if self.sync:
            self.import_queries()
    
    def query_changed(self):
        self.sync = False
        self.send_queries()
            
    def get_queries(self):
        for l, q in self.query_edits:
            l = l.text()
            l = re.sub('[#?]', '', l)
            q = q.text()
            yield [l, q]

    def send_queries(self):
        #if self.send:
        self.queries = list(self.get_queries())
        self.update_queries()
        valid_queries = [[label, query] for label, query in self.queries if not query == '']
        self.send_dictionary(valid_queries) 

    def send_dictionary(self, queries):
        domain = Orange.data.Domain([], metas = [
                                     Orange.data.StringVariable("label"),
                                     Orange.data.StringVariable("query")])
        out = Dictionary(domain, queries)
        self.Outputs.dictionary.send(out)

    def send_output(self, queries):
        domain = Orange.data.Domain([], metas = [
                                 Orange.data.StringVariable("label"),
                                 Orange.data.StringVariable("query")])

    def adjust_n_query_rows(self):
        def _add_line():
            self.query_edits.append([])
            n_lines = len(self.query_edits)
                            
            label_edit = gui.LineEditWFocusOut(self, self.query_changed)
            label_edit.setMaxLength(500000)
            self.query_edits[-1].append(label_edit)
            self.queries_box.addWidget(label_edit, n_lines, 1)

            query_edit = gui.LineEditWFocusOut(self, self.query_changed)
            query_edit.setMaxLength(500000)
            self.query_edits[-1].append(query_edit)
            self.queries_box.addWidget(query_edit, n_lines, 2)

            button = gui.button(
                None, self, label='×', flat=True, height=20,
                styleSheet='* {font-size: 16pt; color: silver}'
                           '*:hover {color: black}',
                autoDefault=False, callback=self.remove_row)
            button.setMinimumSize(QSize(3, 3))
            self.remove_buttons.append(button)
            self.queries_box.addWidget(button, n_lines, 0)
            for coli, kwargs in enumerate(
                    (dict(alignment=Qt.AlignRight),
                     dict(alignment=Qt.AlignLeft, styleSheet="color: gray"))):
                label = QLabel(**kwargs)
                self.queries_box.addWidget(label, n_lines, 3 + coli)

        def _remove_line():
            for edit in self.query_edits.pop():
                edit.deleteLater()
            self.remove_buttons.pop().deleteLater()

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
        self.update_queries()

    def remove_all(self):
        self.queries = []
        self.update_queries()
       
    def update_queries(self):
        self.adjust_n_query_rows()
        self.queries_to_edits()

    def queries_to_edits(self):
        for editr, textr in zip(self.query_edits, self.queries):
            for edit, text in zip(editr, textr):
                edit.setText(text)

    def sync_on_off(self):
        valid_input = self.query_in is not None
        if self.sync and valid_input:
            self.Warning.no_query.clear()
            self.import_queries()
            self.sync = True ## ugly workaround around for unsetting sync with append_queries
            #self.send = True
            self.send_queries()
        else:
            self.Error.no_query()
            #self.send=False
            self.sync = False ## disable synchronize if label_in or query_in are not specified


    def import_queries(self):
        self.queries = []
        self.append_queries()
        
    def append_queries(self):
        self.sync = False
        self.send = False
        label_col = self.querytable_vars2[self.label_in[0]] if not self.label_in[0] is None else None
        query_col = self.querytable_vars[self.query_in[0]] if not self.query_in[0] is None else None
        weight_col = self.querytable_vars2[self.weight_in[0]] if not self.weight_in[0] is None else None
        if label_col == '[not used]': label_col = None
        if weight_col == '[not used]': weight_col = None

        if self.querytable is not None and query_col is not None:
            self.Error.no_query.clear()
            add_queries = self.querytable.import_dictionary(label_col, query_col, weight_col, self.add_quotes)
            self.queries = self.queries + add_queries
            self.update_queries()
        else:
            self.Error.no_query()
        self.send_queries()

    @Inputs.data
    def set_data(self, data):
        if data is not None:
            self.querytable = Dictionary(data)
            self.querytable_attr = self.querytable.attrnames()
            self.querytable_meta = self.querytable.metanames()
            self.querytable_vars = self.querytable_attr + self.querytable_meta
            self.querytable_vars2 = ['[not used]'] + self.querytable_vars
        else:
            self.querytable = None
            self.querytable_attr, self.querytable_metas, self.querytable_vars, self.querytable_vars2 = [], [], [], []
            self.label_in, self.query_in = [None], [None]



class Dictionary(Orange.data.Table):
    """Internal class for storing a dictionary."""

    def attrnames(self):
        return [x.name for x in self.domain.attributes]

    def metanames(self):
        return [x.name for x in self.domain.metas]

    def get_column(self, name):
        for i, a in enumerate(self.attrnames()):
            if a == name:   
                return [str(v[0]) for v in self[:,i]]   
        for i, m in enumerate(self.metanames()):
            if m == name:
                return self.metas[:,i]  ## metas is in numpy format, so this already returns simple list

    def get_dictionary(self, label_col='label', query_col='query'):
        label = self.get_column(label_col)
        query = self.get_column(query_col)
        return [list(a) for a in zip(label,query)]

    def import_dictionary(self, label_col='label', query_col='query', weight_col='weight', add_quotes=True):
        query = self.get_column(query_col)
        #if label_col is None: label_col = weight_col  ## special case where weight is sentiment score
        label = self.get_column(label_col) if label_col is not None else ["no label"] * len(query)
        weight = self.get_column(weight_col) if weight_col is not None else [1] * len(query)

        qdict = {}
        for l, q, w in zip(label, query, weight):
            q = clean_query(q)
            if can_float(l):
                l = 'positive' if float(l) > 0 else 'negative'
            if add_quotes:
                if not '"' in q and len(q.split()) > 1:
                    q = '"' + q + '"'
            else:
                if len(q.split()) > 1:
                    q = '(' + q + ')'
            if can_float(w):
                w = float(w)
                if not w == 1:
                    if w < 0 and not l == 'negative':
                        l = l + ' (negative)'
                    ## regex to add weight to (phrases wrapped in quotes) or (single terms except OR/AND/NOT)
                    q = re.sub(r'(\"[^\"]*\")|([^ \(\)(OR)(AND)(NOT)]+)', r'\1\2^' + str(abs(w)), q)

            qdict[l] = q if not l in qdict.keys() else qdict[l] + ' OR ' + q

        return [[k, v] for k,v in qdict.items()]


def can_float(x):
    try:
        float(x)
        return(True)
    except ValueError:
        return(False)

def clean_query(q):
    q = re.sub('”|“', '"', q)
    return q

if __name__ == '__main__':
    app = QApplication([])
    widget = OWDictionary()
    widget.show()
    app.exec()
    widget.saveSettings()
