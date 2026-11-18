"""Publisher feeds only: FXStreet headlines and Forex Factory high-impact calendar."""
import hashlib
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from threading import Lock
from urllib.parse import urljoin, urlparse
from .energy_service import download, plain, categories, headline_sentiment, official_news, news_window

FX_URL='https://xml.fxstreet.com/news/forex-news/index.xml'
FF_URL='https://nfs.faireconomy.media/ff_calendar_thisweek.json'
_fx_lock,_ff_lock=Lock(),Lock()
_fx_cache=None
_fx_at=0.0
_ff_cache=None
_ff_at=0.0


def parsed_time(text):
    try:
        dt=parsedate_to_datetime(text)
    except (TypeError,ValueError,OverflowError):
        dt=datetime.fromisoformat(text.replace('Z','+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Publisher time zone missing')
    return dt.astimezone(timezone.utc).isoformat()


def parse_fxstreet(content):
    if b'<!doctype' in content.lower() or b'<!entity' in content.lower():
        raise ValueError('Unsupported XML declarations')
    root=ET.fromstring(content)
    items={}
    for node in root.findall('.//item'):
        title=plain(node.findtext('title'))
        link=urljoin('https://www.fxstreet.com/',(node.findtext('link') or '').strip())
        if link.startswith('http://'):link='https://'+link[7:]
        host=(urlparse(link).hostname or '').lower()
        if not title or urlparse(link).scheme!='https' or not (host=='fxstreet.com' or host.endswith('.fxstreet.com')):
            continue
        try:published=parsed_time(node.findtext('pubDate') or '')
        except (ValueError,TypeError,OverflowError):continue
        sentiment=headline_sentiment(title)
        topics=list(dict.fromkeys(['Market']+categories(title+' '+plain(node.findtext('description')))))
        items[link]={'id':'fx-'+hashlib.sha256(link.encode()).hexdigest()[:16], 'title':title,'url':link,
                     'published_at':published,'source':'FXStreet','categories':topics,
                     'tag':sentiment['label'],'sentiment':sentiment,'kind':'article'}
    return list(items.values())


def parse_factory(content):
    data=json.loads(content)
    if not isinstance(data,list):raise ValueError('Expected calendar array')
    events={}
    for row in data:
        if not isinstance(row,dict) or str(row.get('impact','')).strip().lower()!='high':continue
        title=plain(str(row.get('title') or ''))
        currency=plain(str(row.get('country') or ''))
        if not title:continue
        try:scheduled=parsed_time(str(row.get('date') or ''))
        except (ValueError,TypeError,OverflowError):continue
        uid=hashlib.sha256(f'{title}|{currency}|{scheduled}'.encode()).hexdigest()[:16]
        events[uid]={'id':'ff-'+uid,'title':title,'currency':currency,'scheduled_at':scheduled,
                     'source':'Forex Factory','impact':'High','kind':'calendar',
                     'forecast':plain(str(row.get('forecast') or '')),
                     'previous':plain(str(row.get('previous') or '')),
                     # The public weekly export does not supply actual release figures.
                     'actual':None,'url':'https://www.forexfactory.com/calendar'}
    return sorted(events.values(),key=lambda item:item['scheduled_at'])


def refresh_feed(kind):
    global _fx_cache,_fx_at,_ff_cache,_ff_at
    lock=_fx_lock if kind=='fxstreet' else _ff_lock
    with lock:
        previous=_fx_cache if kind=='fxstreet' else _ff_cache
        fetched=_fx_at if kind=='fxstreet' else _ff_at
        ttl=300 if kind=='fxstreet' else 900
        if previous is not None and time.monotonic()-fetched<ttl:return previous
        try:
            items=parse_fxstreet(download(FX_URL,3_000_000)) if kind=='fxstreet' else parse_factory(download(FF_URL,3_000_000))
            result={'status':'ok','items':items,'fetched_at':datetime.now(timezone.utc).isoformat()}
        except Exception:
            label='FXStreet RSS' if kind=='fxstreet' else 'Forex Factory weekly calendar'
            result=dict(previous,status='stale',error=f'{label} refresh failed; showing last downloaded data.') if previous and previous.get('items') else {'status':'unavailable','items':[],'error':f'{label} is unavailable or blocked by the provider.'}
        if kind=='fxstreet':_fx_cache,_fx_at=result,time.monotonic()
        else:_ff_cache,_ff_at=result,time.monotonic()
        return result


def combined_news():
    from .market_news import market_news
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        extra_job=pool.submit(market_news)
        eia_job=pool.submit(official_news)
        fx_job=pool.submit(refresh_feed,'fxstreet')
        ff_job=pool.submit(refresh_feed,'factory')
        extra=extra_job.result()
        eia=news_window(eia_job.result())
        fx=fx_job.result()
        factory=ff_job.result()
    headlines=news_window({'items':list(eia.get('items',[]))+list(fx.get('items',[]))+extra['items']})
    sources={'eia':{k:v for k,v in eia.items() if k in ('status','error','fetched_at')},
             'fxstreet':{k:v for k,v in fx.items() if k!='items'},
             'forexfactory':{k:v for k,v in factory.items() if k!='items'}}
    sources.update(extra['sources'])
    now=datetime.now(timezone.utc)
    from .news_analysis import in_window, analyze
    events=[dict(item,upcoming=datetime.fromisoformat(item['scheduled_at'])>=now) for item in factory.get('items',[]) if in_window(item.get('scheduled_at'),now)]
    available=bool(headlines['items'] or events)
    failures=[name for name,status in sources.items() if status.get('status') not in ('ok','partial')]
    return dict(headlines,source='Official market feeds + EIA + FXStreet + Forex Factory',calendar_events=events,sources=sources,analysis=analyze(headlines['items']),
                status='partial' if failures and available else 'unavailable' if failures else 'ok',
                error='; '.join(sources[name].get('error',name+' unavailable') for name in failures) if not available and failures else None,
                coverage='Today and yesterday IST only. Calendar lists elapsed scheduled events, not verified release outcomes.')
