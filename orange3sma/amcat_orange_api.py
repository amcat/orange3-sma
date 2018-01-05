import requests
import math
import json

from Orange import data
from orangecontrib.text.corpus import Corpus


ARTICLES_PER_PAGE = 1000

class AmcatCredentials:
    """ The AmCAT API credentials. """
    def __init__(self, host, username, password, token):
        self.host = host
        if token == '': token = self.get_token(host, username, password)
        self.token = token

    def get_token(self, host, username, password):
        url = "{}/api/v4/get_token".format('https://amcat.nl')
        r = requests.post(url, data={'username': username, 'password': password})        
        if r.status_code == 200:
            return json.loads(r.text)['token']
        else:
            return ''
            
    @property
    def valid(self):
        ## this should be replaced by a proper check of the token, but this is not working well in current amcat release
        return not self.token == ''

    def __eq__(self, other):
        return self.token == other.token


class AmcatOrangeAPI:
    attributes = []
    class_vars = []
    metas = [(data.StringVariable('Headline'), lambda doc: doc['headline']),
             (data.StringVariable('Byline'), lambda doc: doc['byline']),
             (data.StringVariable('Content'), lambda doc: doc['text']),
             (data.StringVariable('Article_id'), lambda doc: doc['id']),
             (data.StringVariable('Medium'), lambda doc: doc['medium']),
             (data.TimeVariable('Publication Date'), lambda doc: doc['date'])]

    text_features = [metas[0][0], metas[1][0], metas[2][0]]  # names of text columns: Headline + byine + Content
    title_indices = [-1]                        # Headline

    def __init__(self, credentials, on_progress=None, should_break=None):
        """
        Args:
            credentials (:class:`AmcatCredentials`): The AmCAT Credentials.
            on_progress (callable): Function for progress reporting.
            should_break (callable): Function for early stopping.
        """
        self.per_page = ARTICLES_PER_PAGE
        self.pages = 0
        self.credentials = credentials
        self.on_progress = on_progress or (lambda x, y: None)
        self.should_break = should_break or (lambda: False)
        self.results = []

    def _search(self, project, articleset, query, from_date, to_date, page=1):
        columns = ['medium','headline','byline','id','date','text']
        url, options, headers, data = self._build_query(project, articleset, query, from_date, to_date, columns, page)

        response = requests.get(url, data=data, params=options, headers=headers)
        parsed = json.loads(response.text)

        if page == 1:   # store number of pages
            self.pages = parsed['pages']

        self.results.extend(parsed['results'])

    def _build_query(self, project, articleset, query, from_date, to_date, columns, page):
        url = '{}/api/v4/search'.format(self.credentials.host)
        options = {'format': 'json', 'page_size': self.per_page, 'page': page}
        headers = {'Authorization': 'Token {}'.format(self.credentials.token)}
        data = {'project': project, 'sets': articleset, 'col': columns,
                'q': query or '', 'start_date': from_date or '', 'end_date': to_date or ''}

        return url, options, headers, data

    def search(self, project, articleset, query=None, from_date=None, to_date=None, max_documents=None, accumulate=False):
        """
        Search The AmCAT API for articles.

        Args:
            project (int): the project id
            articleset (int): the articleset id
            query (str): A lucene query for searching the articles
            from_date (str): Search only articles newer than the date provided.
                Date should be in ISO format; e.g. '2016-12-31'.
            to_date (str): Search only articles older than the date provided.
                Date should be in ISO format; e.g. '2016-12-31'.
            max_documents (int): Maximum number of documents to retrieve.
                When not given, retrieve all documents.
            accumulate (bool): A flag indicating whether to accumulate results
                of multiple consequent search calls.

        Returns:
            :ref:`Corpus`
        """
        if not accumulate:
            self.results = []

        self._search(project, articleset, query, from_date, to_date, page=1)

        pages = math.ceil(max_documents/self.per_page) if max_documents else self.pages
        self.on_progress(self.per_page, pages * self.per_page)

        for p in range(2, pages+1):
            if self.should_break():
                break
            self._search(project, articleset, query, from_date, to_date, p)
            self.on_progress(p*self.per_page, pages * self.per_page)
        
        c = Corpus.from_documents(self.results, 'AmCAT', self.attributes, self.class_vars, self.metas, self.title_indices)
        c.set_text_features(self.text_features)
        return c



if __name__ == '__main__':
    cred = AmcatCredentials('https://amcat.nl','kasper','xxx')
    api = AmcatOrangeAPI(cred)
    test = api.search(1,1,'test')


