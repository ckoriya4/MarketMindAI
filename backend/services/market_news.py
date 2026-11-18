"""RSS/Atom aggregation. Only headlines, attribution and publisher links are exposed."""
import calendar
import hashlib
import json
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import Lock
from urllib.parse import urljoin, urlsplit
from .energy_service import download, plain, categories, headline_sentiment, news_window

# Endpoints can be overridden without editing application code.
FEEDS = [
 ('nse','NSE','https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml',['Stocks'],True),
 ('rbi','RBI','https://www.rbi.org.in/pressreleases_rss.xml',['Policy'],True),
 ('rbi_notifications','RBI','https://www.rbi.org.in/notifications_rss.xml',['Policy'],True),
 ('sebi','SEBI','https://www.sebi.gov.in/sebirss.xml',['Policy'],True),
 ('pib','PIB','https://www.pib.gov.in/RssMain.aspx?mod=6&lang=1&reg=1',['Policy'],True),
 ('fed','Federal Reserve','https://www.federalreserve.gov/feeds/press_all.xml',['Policy'],False),
 ('bls_jobs','US BLS','https://www.bls.gov/feed/empsit.rss',['Policy'],False),
 ('bls_cpi','US BLS','https://www.bls.gov/feed/cpi_latest.rss',['Policy'],False),
 ('bse','BSE','',['Stocks'],True),
 ('moneycontrol','Moneycontrol','',['Market','Stocks'],True),
 ('et','Economic Times','',['Market','Stocks'],True),
 ('mint','Mint','',['Market','Stocks'],True),
 ('reuters','Reuters / LSEG','',['Market'],False),
]
_lock=Lock()
_cached=None
_cached_at=0
DB=Path(__file__).resolve().parent.parent/'data'/'news-headlines.sqlite3'


def local_name(tag): return tag.rsplit('}',1)[-1].lower()


def published_time(value, india=False):
    value=value.strip().replace(' IST',' +0530')
    try: dt=parsedate_to_datetime(value)
    except (ValueError,TypeError,OverflowError):
        try: dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:
            dt=None
            for fmt in ('%d-%b-%Y %H:%M:%S','%d %b %Y %H:%M:%S','%d/%m/%Y %H:%M:%S'):
                try: dt=datetime.strptime(value,fmt); break
                except ValueError: pass
            if dt is None: raise ValueError('Unrecognized publication time')
    if dt.tzinfo is None:
        if not india: raise ValueError('Missing publication timezone')
        dt=dt.replace(tzinfo=timezone(timedelta(hours=5,minutes=30)))
    return dt.astimezone(timezone.utc).isoformat()


def parse_feed(content, key, source, base, topics, india=False):
    if b'<!doctype' in content.lower() or b'<!entity' in content.lower():
        raise ValueError('XML declarations not accepted')
    root=ET.fromstring(content)
    if local_name(root.tag) not in ('rss','feed','rdf'): raise ValueError('Expected RSS or Atom')
    result=[]; skipped=0
    for node in root.iter():
        if local_name(node.tag) not in ('item','entry'): continue
        values={local_name(c.tag): ''.join(c.itertext()).strip() for c in node}
        title=plain(values.get('title',''))
        link=values.get('link','')
        for c in node:
            if local_name(c.tag)=='link' and c.attrib.get('rel','alternate')=='alternate' and c.attrib.get('href'):
                link=c.attrib['href']; break
        link=urljoin(base,link)
        u=urlsplit(link)
        if not title or u.scheme not in ('http','https') or not u.hostname or u.username:
            skipped+=1; continue
        try: published=published_time(values.get('pubdate') or values.get('published') or values.get('date') or values.get('updated') or '',india)
        except (ValueError,TypeError,OverflowError): skipped+=1; continue
        sentiment=headline_sentiment(title)
        result.append(dict(id=key+'-'+hashlib.sha256(link.encode()).hexdigest()[:20],title=title,url=link,
            published_at=published,source=source,categories=list(dict.fromkeys(['Market']+topics+categories(title))),
            tag=sentiment['label'],sentiment=sentiment,kind='article',source_key=key))
    return result,skipped


def fetch_one(spec):
    key,name,default,topics,india=spec
    url=os.getenv('NEWS_'+key.upper()+'_URL',default).strip()
    if not url:
        return key,{'status':'not_configured','items':[],'error':f'{name}: set NEWS_{key.upper()}_URL to an authorized RSS/Atom feed.'}
    if urlsplit(url).scheme!='https':
        return key,{'status':'unavailable','items':[],'error':f'{name}: HTTPS feed required.'}
    try:
        items,skipped=parse_feed(download(url,4_000_000),key,name,url,topics,india)
        return key,dict(status='partial' if skipped else 'ok',items=items,skipped=skipped,
            fetched_at=datetime.now(timezone.utc).isoformat())
    except Exception:
        return key,dict(status='unavailable',items=[],error=f'{name}: feed blocked, invalid or unreachable; check feed URL.')


def archive(results, path=None):
    path=Path(path or DB); path.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path,timeout=15) as db:
        db.execute('CREATE TABLE IF NOT EXISTS headlines (url TEXT PRIMARY KEY, source_key TEXT, published TEXT, payload TEXT)')
        for key,result in results:
            for item in news_window({'items':result.get('items',[])})['items']:
                db.execute('INSERT OR REPLACE INTO headlines VALUES (?,?,?,?)',(item['url'],key,item['published_at'],json.dumps(item)))
        cutoff=(datetime.now(timezone.utc)-timedelta(days=11)).isoformat()
        db.execute('DELETE FROM headlines WHERE published < ?',(cutoff,))
        rows=[(key,json.loads(payload)) for key,payload in db.execute('SELECT source_key,payload FROM headlines')]
    return rows


def market_news():
    global _cached,_cached_at
    with _lock:
        if _cached is not None and time.monotonic()-_cached_at<60: return _cached
        with ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(fetch_one,FEEDS))
        sources={k:{a:b for a,b in r.items() if a!='items'} for k,r in results}
        try: saved=archive(results)
        except (OSError,sqlite3.Error):
            saved=[(k,i) for k,r in results for i in r.get('items',[])]
            sources['archive']={'status':'unavailable','error':'News archive cannot be written; showing downloaded feeds only.'}
        for key in list(sources):
            if sources[key]['status']=='unavailable' and any(k==key for k,_ in saved): sources[key]['status']='stale'
        _cached={'items':news_window({'items':[i for _,i in saved]})['items'],'sources':sources}
        _cached_at=time.monotonic()
        return _cached
