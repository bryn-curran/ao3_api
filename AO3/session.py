from functools import cached_property

import requests
from bs4 import BeautifulSoup

from . import threadable, utils
from .requester import requester
from .series import Series
from .users import User
from .works import Work
from .search import Search


class GuestSession:
    """
    AP3 guest session object
    """

    def __init__(self):
        self.is_authed = False
        self.authenticity_token = None
        self.username = ""
        self.session = requests.Session()
    
    @threadable.threadable
    def comment(self, chapterid, comment_text, oneshot=False, commentid=None):
        """Leaves a comment on a specific work.
        This function is threadable.

        Args:
            chapterid (str/int): Chapter id
            comment_text (str): Comment text (must have between 1 and 10000 characters)
            oneshot (bool): Should be True if the work has only one chapter. In this case, chapterid becomes workid
            commentid (str/int): If specified, the comment is posted as a reply to this one. Defaults to None.

        Raises:
            utils.InvalidIdError: Invalid workid
            utils.UnexpectedResponseError: Unknown error
            utils.PseudoError: Couldn't find a valid pseudonym to post under
            utils.DuplicateCommentError: The comment you're trying to post was already posted
            ValueError: Invalid name/email

        Returns:
            requests.models.Response: Response object
        """
        
        response = utils.comment(chapterid, comment_text, self, oneshot, commentid)
        return response
    
    
    @threadable.threadable
    def kudos(self, workid):
        """Leave a 'kudos' in a specific work.
        This function is threadable.

        Args:
            workid (int/str): ID of the work

        Raises:
            utils.UnexpectedResponseError: Unexpected response received
            utils.InvalidIdError: Invalid workid (work doesn't exist)

        Returns:
            bool: True if successful, False if you already left kudos there
        """
        
        return utils.kudos(workid, self)
        
    @threadable.threadable
    def refresh_auth_token(self):
        """Refreshes the authenticity token.
        This function is threadable.

        Raises:
            utils.UnexpectedResponseError: Couldn't refresh the token
        """
        
        # For some reason, the auth token in the root path only works if you're 
        # unauthenticated. To get around that, we check if this is an authed
        # session and, if so, get the token from the profile page.
        
        if self.is_authed:
            req = self.session.get(f"https://archiveofourown.org/users/{self.username}")
        else:
            req = self.session.get("https://archiveofourown.org")
            
        if req.status_code == 429:
            raise utils.HTTPError("We are being rate-limited. Try again in a while or reduce the number of requests")
            
        soup = BeautifulSoup(req.content, "lxml")
        token = soup.find("input", {"name": "authenticity_token"})
        if token is None:
            raise utils.UnexpectedResponseError("Couldn't refresh token")
        self.authenticity_token = token.attrs["value"]
        
    def get(self, *args, **kwargs):
        """Request a web page and return a Response object"""  
        
        if self.session is None:
            req = requester.request("get", *args, **kwargs)
        else:
            req = requester.request("get", *args, **kwargs, session=self.session)
        if req.status_code == 429:
            raise utils.HTTPError("We are being rate-limited. Try again in a while or reduce the number of requests")
        return req

    def request(self, url):
        """Request a web page and return a BeautifulSoup object.

        Args:
            url (str): Url to request

        Returns:
            bs4.BeautifulSoup: BeautifulSoup object representing the requested page's html
        """

        req = self.get(url)
        soup = BeautifulSoup(req.content, "lxml")
        return soup

    def post(self, *args, **kwargs):
        """Make a post request with the current session

        Returns:
            requests.Request
        """

        req = self.session.post(*args, **kwargs)
        if req.status_code == 429:
            raise utils.HTTPError("We are being rate-limited. Try again in a while or reduce the number of requests")
        return req
    
    def __del__(self):
        self.session.close()

class Session(GuestSession):
    """
    AO3 session object
    """

    def __init__(self, username, password):
        """Creates a new AO3 session object

        Args:
            username (str): AO3 username
            password (str): AO3 password

        Raises:
            utils.LoginError: Login was unsucessful (wrong username or password)
        """

        super().__init__()
        self.is_authed = True
        self.username = username
        self.url = "https://archiveofourown.org/users/%s"%self.username
        
        self.session = requests.Session()
        
        soup = self.request("https://archiveofourown.org/users/login")
        self.authenticity_token = soup.find("input", {'name': 'authenticity_token'})['value']
        payload = {'user[login]': username,
                   'user[password]': password,
                   'authenticity_token': self.authenticity_token}
        post = self.post("https://archiveofourown.org/users/login", params=payload, allow_redirects=False)
        if not post.status_code == 302:
            raise utils.LoginError("Invalid username or password")

        self._subscriptions_url = "https://archiveofourown.org/users/{0}/subscriptions?page={1:d}"
        self._bookmarks_url = "https://archiveofourown.org/users/{0}/bookmarks?page={1:d}"
        
        self._bookmarks = None
        self._subscriptions = None
        
    def clear_cache(self):
        for attr in self.__class__.__dict__:
            if isinstance(getattr(self.__class__, attr), cached_property):
                if attr in self.__dict__:
                    delattr(self, attr)
        self._bookmarks = None
        self._subscriptions = None
        
    @cached_property
    def _subscription_pages(self):
        url = self._subscriptions_url.format(self.username, 1)
        soup = self.request(url)
        pages = soup.find("ol", {"title": "pagination"})
        if pages is None:
            return 1
        n = 1
        for li in pages.findAll("li"):
            text = li.getText()
            if text.isdigit():
                n = int(text)
        return n
    
    def get_work_subscriptions(self, use_threading=False):
        """
        Get subscribed works. Loads them if they haven't been previously

        Returns:
            list: List of work subscriptions
        """
        
        subs = self.get_subscriptions(use_threading)
        return list(filter(lambda obj: isinstance(obj, Work), subs))
    
    def get_series_subscriptions(self, use_threading=False):
        """
        Get subscribed series. Loads them if they haven't been previously

        Returns:
            list: List of series subscriptions
        """
        
        subs = self.get_subscriptions(use_threading)
        return list(filter(lambda obj: isinstance(obj, Series), subs))
    
    def get_user_subscriptions(self, use_threading=False):
        """
        Get subscribed users. Loads them if they haven't been previously

        Returns:
            list: List of users subscriptions
        """
        
        subs = self.get_subscriptions(use_threading)
        return list(filter(lambda obj: isinstance(obj, User), subs))
    
    def get_subscriptions(self, use_threading=False):
        """
        Get user's subscriptions. Loads them if they haven't been previously

        Returns:
            list: List of subscriptions
        """
        
        if self._subscriptions is None:
            if use_threading:
                self.load_subscriptions_threaded()
            else:
                self._subscriptions = []
                for page in range(self._subscription_pages):
                    self._load_subscriptions(page=page+1)
        return self._subscriptions
    
    @threadable.threadable
    def load_subscriptions_threaded(self):
        """
        Get subscribed works using threads.
        This function is threadable.
        """ 
        
        threads = []
        self._subscriptions = []
        for page in range(self._subscription_pages):
            threads.append(self._load_subscriptions(page=page+1, threaded=True))
        for thread in threads:
            thread.join()

    @threadable.threadable
    def _load_subscriptions(self, page=1):        
        url = self._subscriptions_url.format(self.username, page)
        soup = self.request(url)
        subscriptions = soup.find("dl", {'class': 'subscription index group'})
        for sub in subscriptions.find_all("dt"):
            type_ = "work"
            user = None
            series = None
            workid = None
            workname = None
            authors = []
            for a in sub.find_all("a"):
                if 'rel' in a.attrs.keys():
                    if "author" in a['rel']:
                        authors.append(User(a.string, load=False))
                elif a['href'].startswith("/works"):
                    workname = a.string
                    workid = utils.workid_from_url(a['href'])
                elif a['href'].startswith("/users"):
                    type_ = "user"
                    user = User(a.string, load=False)
                else:
                    type_ = "series"
                    workname = a.string
                    series = int(a['href'].split("/")[-1])
            if type_ == "work":
                new = Work(workid, load=False)
                setattr(new, "title", workname)
                setattr(new, "authors", authors)
                self._subscriptions.append(new)
            elif type_ == "user":
                self._subscriptions.append(user)
            elif type_ == "series":
                new = Series(series, load=False)
                setattr(new, "name", workname)
                setattr(new, "authors", authors)
                self._subscriptions.append(new)
    
    @cached_property
    def _bookmark_pages(self):
        url = self._bookmarks_url.format(self.username, 1)
        soup = self.request(url)
        pages = soup.find("ol", {"title": "pagination"})
        if pages is None:
            return 1
        n = 1
        for li in pages.findAll("li"):
            text = li.getText()
            if text.isdigit():
                n = int(text)
        return n
    
    def get_bookmarks(self, use_threading=False):
        """
        Get bookmarked works. Loads them if they haven't been previously

        Returns:
            list: List of tuples (workid, workname, authors)
        """
        
        if self._bookmarks is None:
            if use_threading:
                self.load_bookmarks_threaded()
            else:
                self._bookmarks = []
                for page in range(self._bookmark_pages):
                    self._load_bookmarks(page=page+1)
        return self._bookmarks
    
    @threadable.threadable
    def load_bookmarks_threaded(self):
        """
        Get bookmarked works using threads.
        This function is threadable.
        """ 
        
        threads = []
        self._bookmarks = []
        for page in range(self._bookmark_pages):
            threads.append(self._load_bookmarks(page=page+1, threaded=True))
        for thread in threads:
            thread.join()
    
    @threadable.threadable
    def _load_bookmarks(self, page=1):       
        url = self._bookmarks_url.format(self.username, page)
        soup = self.request(url)
        bookmarks = soup.find("ol", {'class': 'bookmark index group'})
        for bookm in bookmarks.find_all("li", {'class': 'bookmark blurb group'}):
            authors = []
            for a in bookm.h4.find_all("a"):
                if 'rel' in a.attrs.keys():
                    if "author" in a['rel']:
                        authors.append(User(a.string, load=False))
                elif a.attrs["href"].startswith("/works"):
                    workname = a.string
                    workid = utils.workid_from_url(a['href'])
            
            new = Work(workid, load=False)
            setattr(new, "title", workname)
            setattr(new, "authors", authors)
            if new not in self._bookmarks:
                self._bookmarks.append(new)
            
    @cached_property
    def bookmarks(self):
        """Get the number of your bookmarks.
        Must be logged in to use.

        Returns:
            int: Number of bookmarks
        """

        url = self._bookmarks_url.format(self.username, 1)
        soup = self.request(url)
        div = soup.find("div", {'id': 'inner'})
        span = div.find("span", {'class': 'current'}).getText().replace("(", "").replace(")", "")
        n = span.split(" ")[1]
        
        return int(self.str_format(n))    

    @staticmethod
    def str_format(string):
        """Formats a given string

        Args:
            string (str): String to format

        Returns:
            str: Formatted string
        """

        return string.replace(",", "")
    
    
  def update(self):
        """Sends a request to the AO3 website with the defined search parameters, and updates all info.
        This function is threadable.
        """

        soup = search(
            self.url, self.any_field, self.title, self.author, self.single_chapter,
            self.word_count, self.language, self.fandoms, self.hits,
            self.bookmarks, self.comments, self.completion_status, self.page)

        results = soup.find("ol", {'class': 'work index group'})
        works = []
        for work in results.find_all("li", {'class': 'work blurb group'}):
            authors = []
            for a in work.h4.find_all("a"):
                if 'rel' in a.attrs.keys():
                    if "author" in a['rel']:
                        authors.append(User(a.string, load=False))
                elif a.attrs["href"].startswith("/works"):
                    workname = a.string
                    workid = utils.workid_from_url(a['href'])
                    
            new = Work(workid, load=False)
            setattr(new, "authors", authors)
            setattr(new, "title", workname)
            works.append(new)
            
        self.results = works
        maindiv = soup.find("div", {"class": "works-search region", "id": "main"})
        self.total_results = int(maindiv.find("h3", {"class": "heading"}).getText().strip().split(" ")[0])
        self.pages = ceil(self.total_results / 20)
        
        
def search(
    url="",
    any_field="",
    title="", 
    author="", 
    single_chapter=0, 
    word_count=None, 
    language="", 
    fandoms="", 
    hits=None,
    bookmarks=None,
    comments=None,
    completion_status=None,
    page=1):
    """Returns the results page for the search as a Soup object
    Args:
        any_field (str, optional): Generic search. Defaults to "".
        title (str, optional): Title of the work. Defaults to "".
        author (str, optional): Authors of the work. Defaults to "".
        single_chapter (int, optional): Only include one-shots. Defaults to 0.
        word_count (AO3.utils.Constraint, optional): Word count. Defaults to None.
        language (str, optional): Work language. Defaults to "".
        fandoms (str, optional): Fandoms included in the work. Defaults to "".
        hits (AO3.utils.Constraint, optional): Number of hits. Defaults to None.
        bookmarks (AO3.utils.Constraint, optional): Number of bookmarks. Defaults to None.
        comments (AO3.utils.Constraint, optional): Number of comments. Defaults to None.
        page (int, optional): Page number. Defaults to 1.
    Returns:
        bs4.BeautifulSoup: Search result's soup
    """

    query = utils.Query()
    if page != 1:
        query.add_field(f"page={page}")
    if any_field != "":
        query.add_field(f"work_search[query]={any_field}")
    if title != "":
        query.add_field(f"work_search[title]={title}")
    if author != "":
        query.add_field(f"work_search[creators]={author}")
    if word_count is not None:
        query.add_field(f"work_search[word_count]={word_count}")
    if language != "":
        query.add_field(f"work_search[language_id]={language}")
    if fandoms != "":
        query.add_field(f"work_search[fandom_names]={fandoms}")
    if hits is not None:
        query.add_field(f"work_search[hits_count]={hits}")
    if bookmarks is not None:
        query.add_field(f"work_search[bookmarks_count]={bookmarks}")
    if comments is not None:
        query.add_field(f"work_search[comments_count]={comments}")   
    if completion_status is not None:
        query.add_field(f"work_search[complete]={'T' if completion_status else 'F'}")     
    
    if url == "":
        url = f"https://archiveofourown.org/works/search?{query.string}"
    
    req = requester.request("get", url)
    if req.status_code == 429:
        raise utils.HTTPError("We are being rate-limited. Try again in a while or reduce the number of requests")
    soup = BeautifulSoup(req.content, features="lxml")
    return soup
