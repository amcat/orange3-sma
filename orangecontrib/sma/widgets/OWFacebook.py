from datetime import datetime, timedelta, date
from dateutil import relativedelta


from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import QApplication, QFormLayout, QLabel, QLineEdit, QGridLayout

import Orange
from Orange.widgets.settings import Setting
from Orange.widgets.widget import OWWidget, Msg
from Orange.widgets.credentials import CredentialManager
from Orange.widgets import gui
from Orange.widgets.widget import Input, Output

from orangecontrib.text.corpus import Corpus
from orangecontrib.sma.facebook_orange_api import FacebookCredentials, FacebookOrangeAPI
from orangecontrib.text.widgets.utils import CheckListLayout, QueryBox, DatePickerInterval, ListEdit,  gui_require, asynchronous

DATE_OPTIONS = ["Last week", "Last month", "Last year", "From", "Between"]
LAST_WEEK, LAST_MONTH, LAST_YEAR, DATE_FROM, DATE_BETWEEN = range(len(DATE_OPTIONS))


class OWFacebook(OWWidget):
    class CredentialsDialog(OWWidget):
        name = 'The Facebook Credentials'
        want_main_area = False
        resizing_enabled = False
        cm = CredentialManager('Facebook orange')
        app_id_input = ''
        app_secret_input = ''
        temp_token_input = ''
        token_input = ''
        
        
        class Error(OWWidget.Error):
            invalid_credentials = Msg('These credentials are invalid.')

        def __init__(self, parent):
            super().__init__()
            self.parent = parent
            self.api = None

            self.info = gui.widgetLabel(self.controlArea, 'There are two ways to connect. Either register a Facebook app or obtain a temporary access token. Both require a Facebook account.')
            self.info.setWordWrap(True);

            login_box = gui.hBox(self.controlArea) 
            login_box.setMinimumWidth(300)
            app_login = gui.widgetBox(login_box, box='Option 1: App login')
            temp_login = gui.widgetBox(login_box, box = 'Option 2: Temporary access token')
    
            ## app login
            app_form = QFormLayout()
            app_form.setContentsMargins(5, 5, 5, 5)
            app_info = gui.widgetLabel(app_login, 'To obtain an App ID and secret, <a href=\"https://developers.facebook.com/?advanced_app_create=true\">register</a> a new app (no actual app required). If you already registered an app you need to <a href=\"https://developers.facebook.com/apps/\">visit your app page</a>. The information is on the app dashboard.')
            app_info.setWordWrap(True);                
            app_info.setOpenExternalLinks(True)
            self.app_id_edit = gui.lineEdit(self, self, 'app_id_input', controlWidth=350)           
            self.app_secret_edit = gui.lineEdit(self, self, 'app_secret_input', controlWidth=350)           
            app_form.addRow('App ID:', self.app_id_edit)  
            app_form.addRow('App secret:', self.app_secret_edit)  
            app_login.layout().addLayout(app_form)
            self.submit_button = gui.button(app_login, self, 'Connect', self.app_accept)

            ## temp login
            temp_form = QFormLayout()
            temp_form.setContentsMargins(5, 5, 5, 5)
            temp_info = gui.widgetLabel(temp_login, 'To obtain a temporary (1 hour) access token, visit <a href=\"https://developers.facebook.com/tools/explorer">here</a>. Copy the token (the long line of gibberish) from the "Access Token:" box.')
            temp_info.setWordWrap(True);
            temp_info.setOpenExternalLinks(True)
            self.temp_token_edit = gui.lineEdit(self, self, 'temp_token_input', controlWidth=350)   
            temp_form.addRow('Access Token:', self.temp_token_edit)  
            temp_login.layout().addLayout(temp_form)    
            self.submit_button = gui.button(temp_login, self, 'Connect', self.temp_accept)
        
            self.load_credentials()

        def load_credentials(self):
            if self.cm.token:
                self.token_input = self.cm.token
                if '|' in self.cm.token:
                    token = self.cm.token.split('|')
                    self.app_id_input = token[0]
                    self.app_secret_input = token[1]
                else:
                    self.temp_token_input = self.cm.token
            
        def save_credentials(self):
            self.cm.token = self.token_input
            
        def check_credentials(self, drop_token=True):
            self.credentials = FacebookCredentials(self.token_input)
            self.token_input = self.credentials.token
            self.save_credentials()
            if not self.credentials.valid: self.credentials = None

        def app_accept(self):
            self.token_input = self.app_id_input + '|' + self.app_secret_input
            self.accept()

        def temp_accept(self):
            self.token_input = self.temp_token_input
            self.accept()

        def accept(self, silent=False):
            if not silent: self.Error.invalid_credentials.clear()
            
            self.check_credentials(drop_token = not silent) ## first time loading, use token from last session

            self.parent.update_api(self.credentials)
            if self.credentials:
                super().accept()
            elif not silent:
                self.Error.invalid_credentials()

    name = 'Facebook'
    description = 'Fetch articles from The Facebook Graph API.'
    icon = 'icons/facebook-logo.svg'
    priority = 10

    class Inputs:
        input_posts = Input('Facebook Posts', Orange.data.Table)

    class Outputs:
        posts = Output("Posts Corpus", Corpus)
        comments = Output("Comments Corpus", Corpus)

    want_main_area = False
    resizing_enabled = False

    page_ids = Setting([])
    modes = ['posts','feed']
    mode = Setting(0)
    comments = Setting(0)
    accumulate = Setting(0)
    max_documents = Setting('')

    input_corpus = None

    date_option = Setting(0)
    date_from = Setting(date(1900, 1, 1))
    date_to = datetime.now().date()

    attributes = ['Message','Link name']
    text_includes = Setting(['Message'])

    class Warning(OWWidget.Warning):
        no_text_fields = Msg('Text features are inferred when none are selected.')

    class Error(OWWidget.Error):
        no_api = Msg('Please provide valid login information.')
        no_page_id = Msg('Please enter at least one page ID')
        
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
        self.query_box = gui.widgetBox(self.controlArea, 'Posts', addSpace=True)
        gui.label(self.query_box, self, 'Page IDs (or page URLs)')
        self.query_box.layout().addWidget(ListEdit(self, 'page_ids',
                         'One page ID per line', 80, self))

        def date_changed():
            d.picker_to.setVisible(self.date_option in [DATE_BETWEEN])
            d.picker_from.setVisible(self.date_option in [DATE_FROM, DATE_BETWEEN])
        gui.comboBox(self.query_box, self, 'date_option', items=DATE_OPTIONS, label="Date filter",
                     callback = date_changed)
        date_box = gui.hBox(self.query_box)
        d = DatePickerInterval(date_box, self, 'date_from', 'date_to',
                               min_date=None, max_date=date.today(),
                               margin=(0, 3, 0, 0))
        date_changed()

        self.mode_box = gui.widgetBox(self.query_box, box=True)
        mode_box_h = gui.hBox(self.mode_box)
        gui.radioButtonsInBox(mode_box_h, self, 'mode', btnLabels=['only posts from page itself', 'all public posts on page'], orientation=2)
        # gui.radioButtonsInBox(mode_box_h, self, 'accumulate', btnLabels=['new results', 'add to previous results'], orientation=2, label='On search:')
        gui.lineEdit(mode_box_h, self, 'max_documents', label='Max docs per page:', valueType=str, controlWidth=50)

        comments_box = gui.widgetBox(self.controlArea, box='Comments')
        gui.radioButtonsInBox(comments_box, self, 'comments', btnLabels=['ignore', 'direct comments', 'all comments'], orientation=2)


        # Text includes features
        self.query_box.layout().addWidget(
            CheckListLayout('Text includes', self, 'text_includes',
                            self.attributes,
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
        self.api = FacebookOrangeAPI(api, on_progress=self.progress_with_info,
                                       should_break=self.search.should_break)

    def new_query_input(self):
        self.search.stop()
        self.search()

    def start_stop(self):
        if self.search.running:
            self.search.stop()
        else:
            if self.api.credentials is not None and self.api.credentials.valid:
                self.Error.no_api.clear()
                self.run_search()
            else:
                self.Error.no_api()

    @gui_require('api', 'no_api')
    def run_search(self):
        if len(self.page_ids) == 0 and self.input_corpus is None:
            self.Error.no_page_id()
            return
        else:
            self.Error.no_page_id.clear()
        if not str(self.max_documents).isdigit(): self.max_documents = ''
        self.search()

    @asynchronous
    def search(self):
        mode = self.modes[self.mode]
        max_documents = int(self.max_documents) if not self.max_documents == '' else None
        
        self.date_to = datetime.now().date()
        if self.date_option == LAST_WEEK:
            self.date_from = datetime.now().date() - timedelta(7)
        if self.date_option == LAST_MONTH:
            self.date_from = datetime.now().date() - relativedelta.relativedelta(months=1)
        if self.date_option == LAST_YEAR:
            self.date_from = datetime.now().date() - relativedelta.relativedelta(years=1)
        if self.date_option in [DATE_FROM]:
            self.date_from = self.date_from
        if self.date_option in [DATE_BETWEEN]:
            self.date_to = self.date_to 

        get_comments = self.comments > 0
        get_comment_replies = self.comments > 1
        posts_sub_progress = (0, 0.5) if get_comments else (0, 1)

        if self.input_corpus is None:
            posts = self.api.search(self.page_ids, mode, self.date_from, self.date_to, max_documents=max_documents,
                                    sub_progress=posts_sub_progress)
        else:
            colnames = [x.name for x in self.input_corpus.domain.metas]
            if not 'Post ID' in colnames: return (None, None)
            col_i = colnames.index('Post ID')
            post_ids = list(set(self.input_corpus.metas[:, col_i]))
            posts = self.api.search_posts(post_ids, sub_progress=posts_sub_progress)

        if get_comments:
            colnames = [x.name for x in posts.domain.metas]
            if not 'Post ID' in colnames: return (None, None)
            col_i = colnames.index('Post ID')
            post_ids = list(set(posts.metas[:, col_i]))
            comments = self.api.getComments(post_ids, get_comment_replies, sub_progress=(0.5,1))
        else:
            comments = None
        return (posts, comments)

    @search.callback(should_raise=False)
    def progress_with_info(self, n_retrieved, n_all):
        self.progressBarSet(100 * (n_retrieved / n_all if n_all else 1), None)  # prevent division by 0
        self.output_info = '{}/{}%'.format(n_retrieved, n_all)

    @search.on_start
    def on_start(self):
        self.progressBarInit()
        self.search_button.setText('Stop')
        self.Outputs.posts.send(None)
        self.Outputs.comments.send(None)

    @search.on_result
    def on_result(self, result):
        self.search_button.setText('Search')
        self.progressBarFinished(None)
        self.corpus = result[0]
        self.comments_corpus = result[1]
        self.set_text_features()


    def set_text_features(self):
        self.Warning.no_text_fields.clear()
        if not self.text_includes:
            self.Warning.no_text_fields()

        if self.corpus is not None:
            vars_ = [var for var in self.corpus.domain.metas if var.name in self.text_includes]
            self.corpus.set_text_features(vars_ or None)
            self.Outputs.posts.send(self.corpus)
        if self.comments_corpus is not None:
            self.Outputs.comments.send(self.comments_corpus)

    def send_report(self):
        self.report_items([
            ('Page IDs', self.page_ids),
            ('Date from', self.date_from),
            ('Date to', self.date_to),
            ('Text includes', ', '.join(self.text_includes)),
            ('Output', self.output_info or 'Nothing'),
        ])

    @Inputs.input_posts
    def set_data(self, input_posts):
        if input_posts is not None:
            self.input_corpus = input_posts
            self.query_box.setVisible(False)
            self.mode_box.setVisible(False)
        else:
            self.input_corpus = None
            self.query_box.setVisible(True)
            self.mode_box.setVisible(True)


if __name__ == '__main__':
    app = QApplication([])
    widget = OWFacebook()
    widget.show()
    app.exec()
    widget.saveSettings()

