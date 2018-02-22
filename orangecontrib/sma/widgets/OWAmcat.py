import logging
from datetime import datetime, date
from requests import HTTPError


from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import QApplication, QFormLayout, QLineEdit
from Orange.data import StringVariable, TimeVariable, DiscreteVariable
from Orange.widgets import gui
from Orange.widgets.credentials import CredentialManager
from Orange.widgets.settings import Setting
from Orange.widgets.widget import OWWidget, Msg
from Orange.widgets.widget import Output
from amcatclient import AmcatAPI, APIError
from orangecontrib.text.corpus import Corpus
from orangecontrib.text.widgets.utils import CheckListLayout, DatePickerInterval, ListEdit, gui_require, \
    asynchronous
from orangecontrib.text.widgets.utils.concurrent import StopExecution

DATE_OPTIONS = ["None", "Before", "After", "Between"]
DATE_NONE, DATE_BEFORE, DATE_AFTER, DATE_BETWEEN = range(len(DATE_OPTIONS))


class OWAmcat(OWWidget):
    class CredentialsDialog(OWWidget):
        name = 'The AmCAT Credentials'
        want_main_area = False
        resizing_enabled = False
        cm = CredentialManager('AmCAT orange')
        host_input = 'https://amcat.nl'
        user_input = ''
        passwd_input = ''
        token_input = ''

        class Error(OWWidget.Error):
            invalid_credentials = Msg('These credentials are invalid.')

        def __init__(self, parent):
            super().__init__()
            self.parent = parent
            self.api = None

            form = QFormLayout()
            form.setContentsMargins(5, 5, 5, 5)
            self.host_edit = gui.lineEdit(self, self, 'host_input', controlWidth=150)
            self.user_edit = gui.lineEdit(self, self, 'user_input', controlWidth=150)
            self.passwd_edit = gui.lineEdit(self, self, 'passwd_input', controlWidth=150)
            self.passwd_edit.setEchoMode(QLineEdit.Password)
            
            tokenbox = gui.vBox(self) 
            self.submit_button = gui.button(tokenbox, self, 'request new token', self.accept, width=100)
            self.token_edit = gui.lineEdit(tokenbox, self, 'token_input', controlWidth=200)
            form.addRow('Host:', self.host_edit)
            form.addRow('username:', self.user_edit)
            form.addRow('password:', self.passwd_edit) 

            form.addRow(tokenbox)  
          
            self.controlArea.layout().addLayout(form)
            self.load_credentials()

        def load_credentials(self):
            if self.cm.token:
                self.host_input, self.user_input, self.token_input = self.cm.token.split('\n')   
            
        def save_credentials(self):
            self.cm.token = '{}\n{}\n{}'.format(self.host_input, self.user_input, self.token_input)
            
        def check_credentials(self, drop_token=True):
            if drop_token:
                token = None
            else:
                token = self.token_input or None
            if token or self.passwd_input:
                try:
                    api = AmcatAPI(self.host_input, self.user_input, self.passwd_input, token)
                    if api.token is None: api = None
                except (APIError, HTTPError) as e:
                    logging.exception("Error on getting credentials")
                    api = None
            else:
                api = None
            self.passwd_input = ''
            self.token_input = api and api.token
            self.save_credentials()
            self.api = api

        def accept(self, silent=False):
            if not silent: self.Error.invalid_credentials.clear()
            
            self.check_credentials(drop_token = not silent) ## first time loading, use token from last session   
            self.parent.update_api(self.api) ## always update parent, to enable the user break the token
            if self.api:
                super().accept()
            elif not silent:
                self.Error.invalid_credentials()

    name = 'AmCAT'
    description = 'Fetch articles from The AmCAT API.'
    icon = 'icons/amcat-logo.svg'
    priority = 10

    class Outputs:
        corpus = Output("Corpus", Corpus)

    want_main_area = False
    resizing_enabled = False

    project = Setting('')
    articleset = Setting('')

    date_option = Setting(0)

    query = Setting([])
    max_documents = Setting('')


    date_from = Setting(date(1900, 1, 1))
    date_to = Setting(datetime.now().date())

    text_includes = Setting(['Headline', 'Byline', 'Content'])

    class Warning(OWWidget.Warning):
        no_text_fields = Msg('Text features are inferred when none are selected.')
        search_failed = Msg('Search failed. Try refreshing the token')

    class Error(OWWidget.Error):
        no_api = Msg('Please provide valid login information.')
        no_project = Msg('Please provide a valid (int) project id.')
        no_articleset = Msg('Please provide a valid (int) articleset id.')

    def __init__(self):
        super().__init__()
        self.corpus = None
        self.api = None
        self.output_info = ''

        # API token
        self.api_dlg = self.CredentialsDialog(self)
        self.api_dlg.accept(silent=True)
        gui.button(self.controlArea, self, 'AmCAT login',
                   callback=self.api_dlg.exec_,
                   focusPolicy=Qt.NoFocus)
        # Query
        query_box = gui.widgetBox(self.controlArea, 'Query', addSpace=True)
        aset_box = gui.hBox(query_box)
        project_edit = gui.lineEdit(aset_box, self, 'project', label='Project: ',  orientation=1, valueType=str)
        set_edit = gui.lineEdit(aset_box, self, 'articleset', label='Articleset: ', orientation=1, valueType=str)
        queryset_box = gui.hBox(query_box)
        query_box.layout().addWidget(ListEdit(self, 'query',
                         'One query per line', 80, self))

        # Year box
        def date_changed():
            d.picker_to.setVisible(self.date_option in [DATE_BEFORE, DATE_BETWEEN])
            d.picker_from.setVisible(self.date_option in [DATE_AFTER, DATE_BETWEEN])
        gui.comboBox(query_box, self, 'date_option', items=DATE_OPTIONS, label="Date filter",
                     callback = date_changed)
        date_box = gui.hBox(query_box)
        d = DatePickerInterval(date_box, self, 'date_from', 'date_to',
                               min_date=None, max_date=date.today(),
                               margin=(0, 3, 0, 0))
        date_changed()

        # Text includes features
        self.controlArea.layout().addWidget(
            CheckListLayout('Text includes', self, 'text_includes',
                            ['Headline','Byline', 'Content','Section'],
                            cols=2, callback=self.set_text_features))

        # Output
        info_box = gui.hBox(self.controlArea, 'Output')
        gui.label(info_box, self, 'Articles: %(output_info)s')

        # Buttons
        self.button_box = gui.hBox(self.controlArea)
        self.button_box.layout().addWidget(self.report_button)

        self.search_button = gui.button(self.button_box, self, 'Search',
                                        self.start_stop,
                                        focusPolicy=Qt.NoFocus)

    def update_api(self, api):
        self.Error.no_api.clear()
        self.api = api

    def new_query_input(self):
        self.search.stop()
        self.search()

    def start_stop(self):
        if self.search.running:
            self.search.stop()
        else:
            
            self.run_search()

    @gui_require('api', 'no_api')
    @gui_require('project', 'no_project')
    @gui_require('articleset', 'no_articleset')
    def run_search(self):
        if not str(self.project).isdigit(): self.project = ''
        if not str(self.articleset).isdigit(): self.articleset = ''
        if not str(self.max_documents).isdigit(): self.max_documents = ''
        self.search()
        


    @asynchronous
    def search(self):
        self.Warning.search_failed.clear()
        columns = ['id', 'date', 'medium', 'headline', 'byline', 'section', 'text','creator']
        max_documents = int(self.max_documents) if not self.max_documents == '' else None

        if not self.query and self.date_option == DATE_NONE:
            docs = self.api.get_articles(self.project, self.articleset, columns=columns, yield_pages=True)
        else:
            query = ' OR '.join(['({q})'.format(q=q) for q in self.query])
            filters = {}
            if self.date_option in [DATE_BETWEEN, DATE_AFTER]:
                filters['start_date'] = self.date_from
            if self.date_option in [DATE_BETWEEN, DATE_BEFORE]:
                filters['end_date'] = self.date_to
            docs = self.api.search(project=self.project, articleset=self.articleset, columns=columns,
                                   query=query, yield_pages=True, **filters)
        
        try:
            results = []
            for page in docs:
                results += page['results']
                try:
                    self.progress_with_info(len(results), page['total'])
                except StopExecution:
                    self.output_info = '{}/{} (interrupted)'.format(len(results), page['total'])
                    break
            if results:
                return _corpus_from_results(results)
        except APIError:
            self.Warning.search_failed()
            logging.exception("Error on searching")
        

    @search.callback(should_raise=True)
    def progress_with_info(self, n, total):
        self.output_info = '{n}/{total}'.format(**locals())
        self.progressBarSet(100 * (n / total if total else 1), None)  # prevent division by 0

    @search.on_start
    def on_start(self):
        self.Error.no_project.clear()
        self.Error.no_articleset.clear()

        self.progressBarInit(None)
        self.search_button.setText('Stop')
        self.Outputs.corpus.send(None)

    @search.on_result
    def on_result(self, result):
        self.search_button.setText('Search')
        self.progressBarFinished(None)
        self.corpus = result
        self.set_text_features()

    def set_text_features(self):
        self.Warning.no_text_fields.clear()
        if not self.text_includes:
            self.Warning.no_text_fields()

        if self.corpus is not None:
            vars_ = [var for var in self.corpus.domain.metas if var.name in self.text_includes]
            self.corpus.set_text_features(vars_ or None)
            self.Outputs.corpus.send(self.corpus)

    def send_report(self):
        self.report_items([
            ('Project', self.project),
            ('Articleset', self.articleset),
            ('Query', self.query),
            ('Date from', self.date_from),
            ('Date to', self.date_to),
            ('Text includes', ', '.join(self.text_includes)),
            ('Output', self.output_info or 'Nothing'),
        ])


CORPUS_METAS =[(StringVariable('Headline'), lambda doc: doc.get('headline', '')),
             (StringVariable('Byline'), lambda doc: doc.get('byline', '')),
             (StringVariable('Content'), lambda doc: doc.get('text', '')),
             (StringVariable('Section'), lambda doc: doc.get('section', '')),
             (StringVariable('Article_id'), lambda doc: doc['id']),
             (StringVariable('Creator'), lambda doc: doc.get('creator','')),
             (DiscreteVariable('Medium'), lambda doc: doc.get('medium', '')),
             (TimeVariable('Publication Date'), lambda doc: doc.get('date', ''))]

def _corpus_from_results(docs):
    c = Corpus.from_documents(list(docs), 'AmCAT', attributes=[], class_vars=[], metas=CORPUS_METAS, title_indices=[-1])
    return c


if __name__ == '__main__':
    app = QApplication([])
    widget = OWAmcat()
    widget.show()
    app.exec()
    widget.saveSettings()

