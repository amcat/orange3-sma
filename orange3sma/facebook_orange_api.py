import argparse, sys, os
import requests, json, math
import collections, csv, time
from datetime import datetime, timedelta

from Orange import data
from orangecontrib.text.corpus import Corpus

BASE_URL = 'https://graph.facebook.com'

class FacebookCredentials:
    """ The Facebook API credentials. """
    def __init__(self, token = ''):
        self.token = token
            
    @property
    def valid(self):
        url = BASE_URL + '/facebook/?fields=id'
        headers = {'Authorization': 'Bearer ' + self.token}
        p = requests.get(url, headers=headers)    
        return 'id' in p.json().keys()

class FacebookOrangeAPI():
    attributes = []
    class_vars = []
    image_var = data.StringVariable.make("image")
    image_var.attributes["type"] = "image"
    post_metas = [(data.StringVariable('Message'), lambda doc: doc['status_message']),
             (data.StringVariable('From'), lambda doc: doc['from_name']),
             (data.StringVariable('likes'), lambda doc: doc['like']),
             (data.StringVariable('comments'), lambda doc: doc['comments']),
             (data.StringVariable('shares'), lambda doc: doc['shares']),
             (data.StringVariable('top emotion'), lambda doc: doc['top_reaction']),
             (data.StringVariable('Link name'), lambda doc: doc['link_name']),
             (image_var, lambda doc: doc['picture']),
             (data.StringVariable('link'), lambda doc: doc['status_link']),
             (data.StringVariable('From ID'), lambda doc: doc['from_id']),
             (data.StringVariable('Status ID'), lambda doc: doc['status_id']),
             (data.StringVariable('Status type'), lambda doc: doc['status_type']),
             (data.TimeVariable('Publication Date'), lambda doc: doc['status_published']),
             (data.TimeVariable('Publication Date UTC'), lambda doc: doc['status_published_utc']),
             (data.StringVariable('emotion angry'), lambda doc: doc['angry']),
             (data.StringVariable('emotion love'), lambda doc: doc['love']),
             (data.StringVariable('emotion haha'), lambda doc: doc['haha']),
             (data.StringVariable('emotion wow'), lambda doc: doc['wow']),
             (data.StringVariable('emotion sad'), lambda doc: doc['sad'])]
    text_features = [post_metas[0][0]]
    title_indices = [-1]

    def __init__(self, credentials, on_progress=None, should_break=None):
        self.utc_datecor = datetime.utcnow() - datetime.now() 
        self.pages = 0
        self.credentials = credentials
        self.on_progress = on_progress or (lambda x, y: None)
        self.should_break = should_break or (lambda: False)
        self.results = []

    def buildUrl(self, node, version='v2.11'):
        return BASE_URL + '/' + version + '/' + node  

    def getData(self, url, params=None):
        while True:
            if self.should_break():
                return {}
            try:
                headers = {'Authorization': 'Bearer ' + self.credentials.token}
                p = requests.get(url, params=params, headers=headers)
                return p.json()
            except:                
                print('retry in 5 sec')
                for i in range(50):
                    if self.should_break():
                        return {}
                    time.sleep(0.1)

    def localToUtc(self, date):
        return date + self.utc_datecor

    def utcToLocal(self, date):
        return date - self.utc_datecor
 
    def processStatus(self, status, engagement=True):
        d = {}
        d['status_id'] = status['id']      
        d['from_id'] = status['from']['id']
        d['from_name'] = status['from']['name']        
        d['status_message'] = '' if 'message' not in status.keys() else status['message']
        d['status_type'] = status['type']
        d['link_name'] = '' if 'name' not in status.keys() else status['name']        

        status_published = datetime.strptime(status['created_time'],'%Y-%m-%dT%H:%M:%S+0000')
        d['status_published_utc'] = status_published
        d['status_published'] = self.utcToLocal(status_published)
        d['status_link'] = '' if 'link' not in status.keys() else status['link']
        d['picture'] = status['full_picture'] if 'full_picture' in status.keys() else ''

        topscore = 0
        d['like'] = status['like']['summary']['total_count'] if engagement else ''
        d['comments'] = status['comments']['summary']['total_count'] if engagement else ''
        d['shares'] = status['shares']['count'] if 'shares' in status.keys() else ''

        d['top_reaction'] = ''
        for score in ['love','haha','wow','sad','angry']:
            d[score] = status[score]['summary']['total_count'] if engagement else ''
            if engagement:
                d[score] = status[score]['summary']['total_count']
                if int(d[score]) > topscore:
                    topscore = int(d[score])
                    d['top_reaction'] = score
            else:
                d[score] = ''
                d['top_reaction'] = ''

        return d  
                               
    def fieldString(self, engagement=True):
        field_string = 'message,from,link,created_time,type,name,id,full_picture'
        
        if engagement:
            field_string += ',' + 'comments.limit(0).summary(true),shares.limit(0).summary(true)'
            for r in ['like','love','haha','wow','sad','angry']:
                field_string += ',' + 'reactions.type({}).limit(0).summary(true).as({})'.format(r.upper(), r.lower())
        return field_string
        

    def getStatuses(self, page_id, mode='posts', since=None, until=None, engagement=True, comments=True):
        node = page_id + '/' + mode + '/'  ## mode can be "posts" (posts by page), "feed" (all posts on page) and "tagged" (all public posts in which page is tagged
        url = self.buildUrl(node)

        params = {}
        params['fields'] = self.fieldString(engagement)
        params['limit'] = 100
        
        if since is not None: params['since'] = (self.localToUtc(since)).strftime('%Y-%m-%dT%H:%M:%S') 
        if until is not None: params['until'] = (self.localToUtc(until)).strftime('%Y-%m-%dT%H:%M:%S')
        while True:
            statuses = self.getData(url, params=params)
            if not 'data' in statuses: break

            proc_statuses = [self.processStatus(s, engagement) for s in statuses['data']]            
            yield proc_statuses            

            if not 'paging' in statuses.keys(): break
            if not 'next' in statuses['paging'].keys(): break
            url = statuses['paging']['next']

    def getComments(self, post_ids):
        None

    def _search(self, page_ids, mode, since, until, max_documents):
        since = since.strftime('%Y-%m-%d')
        until = until.strftime('%Y-%m-%d')
        since = datetime.strptime(since, '%Y-%m-%d')
        until = datetime.strptime(until + 'T23:59:59', '%Y-%m-%dT%H:%M:%S')
        total_sec = float((until - since).total_seconds())
        n_pages = len(page_ids)
        
        progress_pct = 1 / float(n_pages)
        
        for page_i in range(0,n_pages):    
            page_id = page_ids[page_i].strip()
            if page_id == '': return
            if '/' in page_id: page_id = page_id.split('/')[-1]
            page_progress = progress_pct * page_i 
            n = 0
            for d in self.getStatuses(page_id, mode, since, until):
                if self.should_break():
                    return
                earliest_date = d[-1]['status_published']
                sec_to_go = (until - earliest_date).total_seconds()
                date_progress = ((sec_to_go / total_sec) * progress_pct)
                progress = math.ceil((page_progress + date_progress)*100)
                self.on_progress(progress, 100)
                for doc in d:
                    n += 1
                    if max_documents is not None:
                        if n > max_documents:
                            break
                    yield doc
                if max_documents is not None:
                    if n > max_documents:
                        break
        self.on_progress(100, 100)

    def search(self, page_ids, mode='posts', since= datetime.now() - timedelta(10), until=datetime.now(), max_documents=None, accumulate=False):
        if not accumulate:
            self.results = []
        
        for doc in self._search(page_ids, mode, since, until, max_documents):
            doc['status_published'] = doc['status_published'].strftime('%Y-%m-%dT%H:%M:%S')
            doc['status_published_utc'] = doc['status_published_utc'].strftime('%Y-%m-%dT%H:%M:%S')
            self.results.append(doc)
             
        c = Corpus.from_documents(self.results, 'Facebook', self.attributes, self.class_vars, self.post_metas, self.title_indices)
        c.set_text_features(self.text_features)
        return c

#if __name__ == '__main__':
#    access_token  = ''
#    cred = FacebookCredentials(access_token)
#    f = FacebookOrangeAPI(cred)
#    for a in f.search(['volkskrant']):
#        None   
