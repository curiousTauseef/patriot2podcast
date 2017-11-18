#!/usr/bin/python3

import sys, os, pickle
import re
from collections import OrderedDict
import time # FIXME sleep till flush cache
import logging, logging.handlers
import urllib.request, urllib.parse

from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

from dateutil import parser
import pytz


### Environment Variables
patriotPickle = "pat.p"             # save parsed feed informations
sys.setrecursionlimit(50000)        # for pickle operation
domainURL = "domain.xyz"

redirTopURL = "http://" + domainURL + "/patriot/redir"

flareURL = 'https://www.cloudflare.com/api_json.html'
flareTokenFile = 'flareKey.tkn'
flareEmail = "cloudflare@account.mail"
flareDomain = domainURL

feedURL = "http://" + domainURL + "/patriot/patriot_feed.xml"
bbangURL = "http://www.podbbang.com/mypage/cast_update?uid=<pod_id>&request=ch"


## simple logger
my_logger = logging.getLogger('MyLogger')
my_logger.setLevel(logging.DEBUG)

handler = logging.handlers.RotatingFileHandler('feed.log', maxBytes=20*1024, backupCount=2)
my_logger.addHandler(handler)


### Utility Functions
def getHTTPContent(URL):
    maxbuf = 10485760   # const
    response = urllib.request.urlopen(URL)
    html = response.read(maxbuf)
    response.close()
    return html

def getHTTPHeader(URL):
    class HeadRequest(urllib.request.Request):
        def get_method(self):
            return "HEAD"

    request = HeadRequest(URL)
    response = urllib.request.urlopen(request)

    header = dict(response.info().items())
    header['URL'] = response.geturl() # NOTE no use of this for retrieve real URL with real filename...
    return header
    
def readHTTPHeader(dictHeader):
    # returns "Content-Type", "Content-Length", "Last-Modified"
    return dictHeader['Content-Type'], dictHeader['Content-Length'], dictHeader['Last-Modified']


class PatriotFeed:
    def __init__(self):
        self.foundNewEpisode = False

        self.initInfo()
        self.initStorage()

    def initInfo(self):
        self.topURL = "http://m.newsfund.media.daum.net"
        self.logoURL = "http://p.talk.kakao.co.kr/th/talkp/wkik8qyEHi/bFkuKlWPcGH3fFC4JwPE4K/2oa6yi_640x640_s.jpg"
        self.projId = "139"

        self.language = 'ko-KR'
        self.categories = ['News & Politics', 'Society & Culture']

        self.title = "(비공식) 제동이와 진우의 애국소년단"
        self.author = '다음 뉴스펀딩'
        self.subtitle = '애국이라는 생각을 켜놓은 채 잠이 들었습니다 (주의: 저작권자의 허락을 받지 않은 피드입니다)'
        self.copyright = '저작권자 (C)애국소년단'

    def initStorage(self):
        self.episodes = OrderedDict()

    ## utility functions
    def genProjURL(self):
        return self.topURL + "/project/" + self.projId

    def genProjEpListURL(self):
        return self.genProjURL() + "/episodes"

    def genEpDetailPageURL(self, epId):
        return self.topURL + "/episode/" + epId

    ## main methods
    def updateEpisodesList(self):
        # init episode
        self.foundNewEpisode = False

        episodesPage = getHTTPContent(self.genProjEpListURL())

        soup = BeautifulSoup(episodesPage)
        items = soup.find_all('a', attrs={'class':"link_thumb"})

        for item in items:
            self.addEpisode(item)

        my_logger.debug(self.episodes)

    def generateFeed(self, feedPath):
        fg = FeedGenerator()
        fg.load_extension('podcast')

        self.setFeedInfo(fg)
        self.appendEpisodesToFeed(fg)

        fg.rss_file(filename=feedPath, pretty=True, encoding='UTF-8')
        # TODO WORKAROUND force add XML declaration at the first on feed file
        # NOTE http://stackoverflow.com/questions/5914627/prepend-line-to-beginning-of-a-file
        with open(feedPath, 'r+') as f:
            content = f.read()
            f.seek(0, 0)
            f.write('<?xml version="1.0" encoding="UTF-8"?>' + '\n' + content)

    ## inner methods
    # add new entry from episode list
    # NOTE additional information e.g. stream URL, ... is added later
    def addEpisode(self, item):
        # NOTE assume episode ID is assigned chronologically
        epId = str(item.attrs['href']).replace(r"/episode/", "")
        my_logger.debug(epId)
        if not epId in self.episodes:
            entry = dict()
            # parse more informations
            entry['id'] = epId
            entry['title'] = item.find(attrs={'class':'tit_thumb'}).get_text()
            entry['thumb_mini'] = item.find('img', attrs={'class':'thumb_g'}).attrs['src']
            entry['thumb'] = re.sub(r'.*fname=(.*)', r'\1', entry['thumb_mini'])
            entry['link'] = self.genEpDetailPageURL(epId)
            entry['check'] = False  # NOTE flags if episode page has not been parsed!
            
            self.getEpisodeDetail(entry)

            self.episodes[epId] = entry

            self.foundNewEpisode = True

    def getEpisodeDetail(self, entry):
        episodePage = getHTTPContent(self.genEpDetailPageURL(entry['id']))
        ep_soup = BeautifulSoup(episodePage)

        entry['article_date_raw'] = ep_soup.find('span', attrs={'class':'txt_bar'}).next_sibling
        entry['article_date'] = pytz.timezone('Asia/Seoul').localize(parser.parse(entry['article_date_raw'])) 
        
        ep_items = ep_soup.find_all('audio')
        entry['stream'] = ""
        if len(ep_items) > 0:
            entry['stream'] = ep_items[0].attrs['src']
            # NOTE Thankfully, Daum CDN server currently ignores appended (garbage-like) strings (@2015-02-27)
            # Because Apple iTunes completely ignores MIME type specified, and determines only with extension in URL,
            # the URL has to end with '.mp3' extension
            # NOTE But because '?' is included in URL, trick that inserting '/episode.mp3' is no use for iTunes
            
            header = getHTTPHeader(entry['stream'])
            entry['stream_type'] = header['Content-Type']
            entry['stream_size'] = header['Content-Length']
            entry['stream_date_raw'] = header['Last-Modified']
            entry['stream_date'] = (parser.parse(entry['stream_date_raw'])).astimezone(pytz.timezone('Asia/Seoul'))


        entry['check'] = True

    def getCategories(self):
        categoryList = list()
        for category in self.categories:
            categoryList.append({'term':category})
        return categoryList

    def setFeedInfo(self, fg):
        fg.id(self.genProjURL())

        fg.language(self.language)
        fg.category(self.getCategories())
        fg.podcast.itunes_category(self.categories[0])
        
        fg.title(self.title)
        fg.author({'name':self.author})
        fg.podcast.itunes_author(self.author)
        fg.subtitle(self.subtitle)
        fg.podcast.itunes_subtitle(self.subtitle)
        fg.copyright(self.copyright)

        fg.link(href=self.genProjURL(), rel='alternate')
        fg.logo(self.logoURL)
        fg.podcast.itunes_image(self.logoURL)

    def appendEpisodesToFeed(self, fg):
        for episode in self.episodes.values():
            self.appendEpisodeToFeed(fg, episode)

    def appendEpisodeToFeed(self, fg, episode):
        if episode['stream'] == "":
            return

        fe = fg.add_entry()

        fe.id(episode['link'])
        fe.podcast.itunes_order(episode['id'])
        fe.podcast.itunes_explicit('no')    # not an adult content :)
        
        fe.title(episode['title'])
        fe.podcast.itunes_author(self.author)
#       fe.podcast.itunes_duration("00:01:00")          # TODO WORKAROUND
#       fe.podcast.itunes_subtitle(episode['title'])    # TODO WORKAROUND
#       fe.podcast.itunes_summary(episode['title'])     # TODO WORKAROUND

        fe.link(href=episode['link'], rel='alternate')
        fe.podcast.itunes_image(episode['thumb'])
        fe.pubdate(episode['article_date'])

        if episode['stream'] != "":
            # WORKAROUND fake URL will be redirected in CloudFlare or Nginx
            fake_URL = re.sub(r'http://(.*)\?(.*)', redirTopURL + r'/\1_\2/episode.mp3', episode['stream'])
            fe.enclosure(url=fake_URL, length=episode['stream_size'], type=episode['stream_type'])

    pass

if __name__ == '__main__':
    # init parser
    pf = PatriotFeed()
    # load previous result if exists
    try:
        if os.path.isfile(patriotPickle):
            with open(patriotPickle, "rb") as f:
                pf = pickle.load(f)
    except:
        pass
   
    # update episodes, generate feed
    pf.initInfo()
    pf.updateEpisodesList()
    pf.generateFeed("patriot_feed.xml")
    
    # save result to pickle
    with open(patriotPickle, "wb") as f:
        pickle.dump(pf, f)
    
    # - flush CloudFlare cache & update Podbbang
    # read CloudFlare token
    f = open(flareTokenFile, 'r')
    flareToken = f.readline().strip()
    f.close()

    if pf.foundNewEpisode:
        my_logger.info("New episodes detected! Flushing cloudFlare cache")

        # flush CloudFlare
        params = {'a':'zone_file_purge', 'tkn':flareToken, 'email':flareEmail, 'z':flareDomain, 'url':feedURL}
        params = urllib.parse.urlencode(params)
        params = params.encode('UTF-8')
        flare = urllib.request.Request(flareURL, params)
        urllib.request.urlopen(flare)
        
        time.sleep(3)   # FIXME wait 3 sec
        
        # update Podbbang
        bbang = urllib.request.Request(bbangURL)
        urllib.request.urlopen(bbang)

    my_logger.info(time.asctime() + '  : new episode=' + str(pf.foundNewEpisode) + '\n')


