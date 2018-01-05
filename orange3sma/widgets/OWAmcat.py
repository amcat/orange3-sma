from datetime import datetime, timedelta, date

from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import QApplication, QFormLayout, QLineEdit

from Orange.data import StringVariable
from Orange.widgets.settings import Setting
from Orange.widgets.widget import OWWidget, Msg
from Orange.widgets.credentials import CredentialManager
from Orange.widgets import gui
from Orange.widgets.widget import Output

from orangecontrib.text.corpus import Corpus
from orange3sma.amcat_orange_api import AmcatCredentials, AmcatOrangeAPI
from orangecontrib.text.widgets.utils import CheckListLayout, QueryBox, DatePickerInterval, ListEdit, gui_require, asynchronous

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
            self.host_edit = gui.lineEdit(self, self, 'host_input', controlWidth=350)
            self.user_edit = gui.lineEdit(self, self, 'user_input', controlWidth=350)
            self.passwd_edit = gui.lineEdit(self, self, 'passwd_input', controlWidth=350)
            self.passwd_edit.setEchoMode(QLineEdit.Password)
            self.token_edit = gui.lineEdit(self, self, 'token_input', controlWidth=350)
            form.addRow('Host:', self.host_edit)
            form.addRow('username:', self.user_edit)
            form.addRow('password:', self.passwd_edit)            
            form.addRow('token:', self.token_edit)  
          
            self.controlArea.layout().addLayout(form)
            
            #token_box = gui.hBox(self.controlArea, 'Token')
            #self.token_edit = gui.label(token_box, self, '%(token_input)s')

            self.submit_button = gui.button(self.controlArea, self, 'request new token', self.accept)

            self.load_credentials()

        def load_credentials(self):
            if self.cm.token:
                self.host_input, self.user_input, self.token_input = self.cm.token.split('\n')   
            
        def save_credentials(self):
            self.cm.token = '{}\n{}\n{}'.format(self.host_input, self.user_input, self.token_input)
            
        def check_credentials(self, drop_token=True):
            if drop_token: self.token_input = ''
            api = AmcatCredentials(self.host_input, self.user_input, self.passwd_input, self.token_input)
            self.passwd_input = ''
            self.token_input = api.token
            self.save_credentials()
            if not api.valid: api = None
            self.api = api

        def accept(self, silent=False):
            if not silent: self.Error.invalid_credentials.clear()
            
            self.check_credentials(drop_token = not silent) ## first time loading, use token from last session
            if self.api:
                self.parent.update_api(self.api)
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
    query = Setting([])
    accumulate = Setting(0)
    max_documents = Setting('')
    date_from = Setting(date(1900,1,1))
    date_to = Setting(datetime.now().date())
    attributes = [feat.name for feat, _ in AmcatOrangeAPI.metas if
                  isinstance(feat, StringVariable)]
    text_includes = Setting([feat.name for feat in AmcatOrangeAPI.text_features])

    class Warning(OWWidget.Warning):
        no_text_fields = Msg('Text features are inferred when none are selected.')

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
        date_box = gui.hBox(query_box)
        DatePickerInterval(date_box, self, 'date_from', 'date_to',
                           min_date=None, max_date=date.today(),
                           margin=(0, 3, 0, 0))

        gui.radioButtonsInBox(query_box, self, 'accumulate', btnLabels=['reset', 'append'], orientation=0, label='On search:')
        gui.lineEdit(query_box, self, 'max_documents', label='Max docs per page:', valueType=str, controlWidth=50)

        # Text includes features
        #self.controlArea.layout().addWidget(
        #    CheckListLayout('Text includes', self, 'text_includes',
        #                    self.attributes,
        #                    cols=2, callback=self.set_text_features))

    

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
        self.api = AmcatOrangeAPI(api, on_progress=self.progress_with_info,
                                       should_break=self.search.should_break)

    def new_query_input(self):
        self.search.stop()
        self.search()

    def start_stop(self):
        if self.search.running:
            self.search.stop()
        else:
            #self.query_box.synchronize(silent=True)
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
        accumulate = self.accumulate == 1
        max_documents = int(self.max_documents) if not self.max_documents == '' else None
        if self.query == '':
            query = ''
        else:
            query = ' OR '.join(['({q})'.format(q=q) for q in self.query])
        return self.api.search(self.project, self.articleset, query, self.date_from, self.date_to)

    @search.callback(should_raise=False)
    def progress_with_info(self, n_retrieved, n_all):
        self.progressBarSet(100 * (n_retrieved / n_all if n_all else 1), None)  # prevent division by 0
        self.output_info = '{}/{}'.format(n_retrieved, n_all)

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


if __name__ == '__main__':
    app = QApplication([])
    widget = OWAmcat()
    widget.show()
    app.exec()
    widget.saveSettings()

