from datetime import datetime, timedelta, date

from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import QApplication, QFormLayout, QLabel, QLineEdit, QGridLayout

from Orange.data import StringVariable
from Orange.widgets.settings import Setting
from Orange.widgets.widget import OWWidget, Msg
from Orange.widgets.credentials import CredentialManager
from Orange.widgets import gui
from Orange.widgets.widget import Output

from orangecontrib.text.corpus import Corpus
from orange3sma.facebook_orange_api import FacebookCredentials, FacebookOrangeAPI
from orangecontrib.text.widgets.utils import CheckListLayout, QueryBox, DatePickerInterval, ListEdit,  gui_require, asynchronous



class OWFacebook(OWWidget):
    class CredentialsDialog(OWWidget):
        name = 'The Facebook Credentials'
        want_main_area = False
        resizing_enabled = False
        cm = CredentialManager('Facebook orange')
        app_id_input = ''
        app_secret_input = ''
        
        class Error(OWWidget.Error):
            invalid_credentials = Msg('These credentials are invalid.')

        def __init__(self, parent):
            super().__init__()
            self.parent = parent
            self.api = None

            form = QFormLayout()
            form.setContentsMargins(5, 5, 5, 5)
            self.app_id_edit = gui.lineEdit(self, self, 'app_id_input', controlWidth=350)           
            self.app_secret_edit = gui.lineEdit(self, self, 'app_secret_input', controlWidth=350)           
            form.addRow('App ID:', self.app_id_edit)  
            form.addRow('App secret:', self.app_secret_edit)  
            self.controlArea.layout().addLayout(form)
            self.submit_button = gui.button(self.controlArea, self, 'Connect', self.accept)

            self.load_credentials()

        def load_credentials(self):
            if self.cm.token:
                token = self.cm.token.split('|')
                self.app_id_input = token[0]
                self.app_secret_input = token[1]
            
        def save_credentials(self):
            self.cm.token = self.app_id_input + '|' + self.app_secret_input
            
        def check_credentials(self, drop_token=True):
            token = self.app_id_input + '|' + self.app_secret_input
            api = FacebookCredentials(token)
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

    name = 'Facebook'
    description = 'Fetch articles from The Facebook Graph API.'
    icon = 'icons/facebook-logo.svg'
    priority = 10

    class Outputs:
        corpus = Output("Corpus", Corpus)

    want_main_area = False
    resizing_enabled = False

    page_ids = Setting([])
    modes = ['posts','feed']
    mode = Setting(0)
    accumulate = Setting(0)
    max_documents = Setting('')
    date_from = Setting(datetime.now().date() - timedelta(30))
    date_to = Setting(datetime.now().date())
    attributes = [feat.name for feat, _ in FacebookOrangeAPI.metas if
                  isinstance(feat, StringVariable)]
    text_includes = Setting([feat.name for feat in FacebookOrangeAPI.text_features])

    class Warning(OWWidget.Warning):
        no_text_fields = Msg('Text features are inferred when none are selected.')

    class Error(OWWidget.Error):
        no_api = Msg('Please provide valid login information.')
        
    def __init__(self):
        super().__init__()
        self.corpus = None
        self.api = None
        self.output_info = ''

        # API token
        self.api_dlg = self.CredentialsDialog(self)
        self.api_dlg.accept(silent=True)
        gui.button(self.controlArea, self, 'Facebook login',
                   callback=self.api_dlg.exec_,
                   focusPolicy=Qt.NoFocus)

        # Query
        query_box = gui.widgetBox(self.controlArea, 'Query', addSpace=True)
        #query_box.layout().addWidget(QLabel('Query'))
        query_box.layout().addWidget(ListEdit(self, 'page_ids',
                         'One page ID per line', 80, self))

        date_box = gui.hBox(query_box)
        DatePickerInterval(date_box, self, 'date_from', 'date_to',
                           min_date=None, max_date=date.today(),
                           margin=(4, 0, 0, 0))

        mode_box = gui.hBox(query_box)
        gui.radioButtonsInBox(query_box, self, 'mode', btnLabels=['only posts from page itself', 'all public posts on page'], orientation=0, label='Mode:')
        gui.radioButtonsInBox(query_box, self, 'accumulate', btnLabels=['reset', 'append'], orientation=0, label='On search:')
        gui.lineEdit(query_box, self, 'max_documents', label='Max docs per page:', valueType=str, controlWidth=50)

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
        self.api = FacebookOrangeAPI(api, on_progress=self.progress_with_info,
                                       should_break=self.search.should_break)

    def new_query_input(self):
        self.search.stop()
        self.search()

    def start_stop(self):
        if self.search.running:
            self.search.stop()
        else:
            self.run_search()

    @gui_require('api', 'no_api')
    
    def run_search(self):
        if not str(self.max_documents).isdigit(): self.max_documents = ''
        self.search()

    @asynchronous
    def search(self):
        mode = self.modes[self.mode]
        accumulate = self.accumulate == 1
        max_documents = int(self.max_documents) if not self.max_documents == '' else None
        return self.api.search(self.page_ids, mode, self.date_from, self.date_to, max_documents=max_documents, accumulate=accumulate)

    @search.callback(should_raise=False)
    def progress_with_info(self, n_retrieved, n_all):
        self.progressBarSet(100 * (n_retrieved / n_all if n_all else 1), None)  # prevent division by 0
        self.output_info = '{}/{}%'.format(n_retrieved, n_all)

    @search.on_start
    def on_start(self):
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
            ('Page IDs', self.page_ids),
            ('Date from', self.date_from),
            ('Date to', self.date_to),
            ('Text includes', ', '.join(self.text_includes)),
            ('Output', self.output_info or 'Nothing'),
        ])


if __name__ == '__main__':
    app = QApplication([])
    widget = OWFacebook()
    widget.show()
    app.exec()
    widget.saveSettings()

