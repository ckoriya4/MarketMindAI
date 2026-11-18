"""Official EIA daily spot prices/news plus optional Kite MCX futures quotes."""
import hashlib
import html
import math
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from threading import Lock
from urllib.parse import urljoin, urlparse

import requests
from fastapi import APIRouter

router = APIRouter()
_price_lock, _news_lock, _mcx_lock = Lock(), Lock(), Lock()
_prices = None
_prices_at = 0.0
_price_attempt = 0.0
_news = None
_news_at = 0.0
_news_attempt = 0.0
_mcx = None
_mcx_at = 0.0
_contract = None
_contract_day = None
_mcx_history = {}
_mcx_observed = {}
SOURCES = {
    'WTI': ('https://www.eia.gov/dnav/pet/hist_xls/RWTCd.xls', 'https://www.eia.gov/dnav/pet/hist/RWTCD.htm'),
    'Brent': ('https://www.eia.gov/dnav/pet/hist_xls/RBRTEd.xls', 'https://www.eia.gov/dnav/pet/hist/RBRTED.htm'),
}
FEEDS = ('https://www.eia.gov/rss/todayinenergy.xml', 'https://www.eia.gov/rss/press_rss.xml')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def download(url, limit):
    with requests.get(url, timeout=(5, 15), stream=True,
                      headers={'User-Agent': 'MarketMind/1.0 (official energy data reader)'}) as response:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > limit:
                raise ValueError('Provider response exceeds expected size')
            chunks.append(chunk)
        return b''.join(chunks)


def summarize_series(points, source_url):
    unique = {p['date']: float(p['value']) for p in points if math.isfinite(float(p['value']))}
    history = [{'date':d, 'value':unique[d]} for d in sorted(unique)]
    if len(history) < 2:
        raise ValueError('Not enough official observations')
    latest, previous = history[-1], history[-2]
    delta = latest['value']-previous['value']
    return {'price':latest['value'], 'as_of':latest['date'], 'change':round(delta, 2),
            'change_pct':round(delta/abs(previous['value'])*100, 2) if previous['value'] else None,
            'previous_date':previous['date'], 'history':history[-30:],
            'currency':'USD', 'unit':'barrel', 'frequency':'daily', 'source':'U.S. EIA', 'url':source_url}


def parse_eia_xls(content, source_url):
    try:
        import xlrd
    except ImportError:
        raise RuntimeError('Install xlrd: python -m pip install xlrd') from None
    book = xlrd.open_workbook(file_contents=content)
    points = []
    for sheet in book.sheets():
        if sheet.ncols < 2:
            continue
        for row in range(sheet.nrows):
            first, second = sheet.cell(row, 0), sheet.cell(row, 1)
            if first.ctype == xlrd.XL_CELL_DATE and second.ctype == xlrd.XL_CELL_NUMBER:
                day = xlrd.xldate_as_datetime(first.value, book.datemode).date()
                if day <= date.today() and math.isfinite(second.value):
                    points.append({'date':day.isoformat(), 'value':second.value})
    return summarize_series(points, source_url)


def official_prices():
    global _prices, _prices_at, _price_attempt
    with _price_lock:
        now = time.monotonic()
        if _prices is not None and now-_prices_at < 1800:
            return dict(_prices, status='ok')
        if now-_price_attempt < 60 and _price_attempt:
            return dict(_prices, status='stale', error='Official price refresh pending') if _prices else {'status':'unavailable','error':'Official EIA data unavailable; retry in one minute.'}
        _price_attempt = now
        try:
            data = {name:parse_eia_xls(download(url, 12_000_000), page) for name,(url,page) in SOURCES.items()}
            _prices = {'series':data, 'fetched_at':stamp(), 'source':'U.S. EIA', 'frequency':'daily'}
            _prices_at = time.monotonic()
            return dict(_prices, status='ok')
        except RuntimeError as error:
            message = str(error)
        except Exception:
            message = 'Cannot refresh official EIA WTI/Brent data. Check internet/provider availability.'
        if _prices:
            return dict(_prices, status='stale', error=message)
        return {'status':'unavailable','error':message,'series':{}}


def mcx_history(kite, contract, quote_time, price, ist):
    """Latest trading date's 5-minute closes; observed quote fallback if history is unavailable."""
    key = contract['tradingsymbol']
    quote_day = datetime.fromtimestamp(quote_time, ist).date()
    observed_key = (key, quote_day.isoformat())
    observed = _mcx_observed.setdefault(observed_key, {})
    observed[quote_time] = price
    cached = _mcx_history.get(observed_key)
    message = None
    if cached and time.monotonic()-cached['at'] < 300:
        points = list(cached['points'])
        message = cached.get('error')
    else:
        try:
            end = datetime.fromtimestamp(quote_time, ist)
            records = kite.historical_data(contract['instrument_token'], end-timedelta(days=7), end, '5minute')
            values = {}
            for r in records:
                dt = r['date']
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ist)
                if dt.date() == quote_day and math.isfinite(float(r['close'])):
                    values[int(dt.timestamp())] = float(r['close'])
            if not values:
                raise ValueError('No historical bars on quote date')
            points = [{'time':ts,'value':values[ts]} for ts in sorted(values)]
        except Exception:
            points = []
            message = 'Historical access unavailable; plotting observed quotes from this server session.'
        _mcx_history[observed_key] = {'at':time.monotonic(),'points':points,'error':message}
    if points:
        # A latest quote is distinct from the timestamped historical candle closes.
        values = {p['time']:p['value'] for p in points}
        values[quote_time] = price
        points = [{'time':ts,'value':values[ts]} for ts in sorted(values)]
        mode = 'Kite 5-minute historical closes + latest quote'
    else:
        points = [{'time':ts,'value':value} for ts,value in sorted(observed.items())]
        mode = 'Kite observed quote history'
    return {'history':points,'history_mode':mode,'history_date':quote_day.isoformat(),'history_error':message}


def mcx_quote():
    global _mcx, _mcx_at, _contract, _contract_day
    with _mcx_lock:
        if _mcx is not None and time.monotonic()-_mcx_at < 30:
            return _mcx
        try:
            from .oi_signal import IST, kite_client, provider_time
            today = datetime.now(IST).date()
            kite = kite_client()
            if _contract_day != today:
                contracts = [i for i in kite.instruments('MCX')
                             if i.get('name') == 'CRUDEOIL' and i.get('instrument_type') == 'FUT'
                             and (i['expiry'].date() if isinstance(i['expiry'], datetime) else i['expiry']) >= today]
                if not contracts:
                    raise ValueError('No MCX crude futures found')
                _contract = min(contracts, key=lambda i:i['expiry'])
                _contract_day = today
            key = f"MCX:{_contract['tradingsymbol']}"
            q = kite.quote([key]).get(key, {})
            price = q.get('last_price')
            if not isinstance(price, (int,float)) or not math.isfinite(price) or price <= 0:
                raise ValueError('Missing MCX price')
            ts = provider_time(q.get('timestamp'))
            close = q.get('ohlc', {}).get('close')
            change = price-close if isinstance(close,(int,float)) and close else None
            fresh = -5 <= time.time()-ts <= 90
            value = {'status':'fresh' if fresh else 'stale', 'price':price, 'currency':'INR',
                     'symbol':_contract['tradingsymbol'], 'expiry':str(_contract['expiry']),
                     'quote_time':ts, 'source':'Kite / MCX',
                     'change':round(change,2) if change is not None else None,
                     'change_pct':round(change/close*100,2) if change is not None else None}
            value.update(mcx_history(kite, _contract, ts, price, IST))
        except Exception:
            value = {'status':'unavailable', 'error':'MCX quote unavailable: check Kite token and MCX market-data access.'}
        _mcx, _mcx_at = value, time.monotonic()
        return value


@router.get('/api/energy/crude')
def crude():
    return {'official':official_prices(), 'mcx':mcx_quote(), 'fetched_at':stamp()}


def plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', value or ''))).strip()


def categories(text):
    text = text.lower()
    result = []
    if re.search(r'\b(crude|petroleum|oil|gasoline|diesel|refiner\w*|brent|wti|opec)\b', text): result.append('Crude')
    if re.search(r'\b(pric\w*|demand|supply|production|imports?|exports?|market\w*)\b', text): result.append('Market')
    if re.search(r'\b(polic\w*|regulat\w*|sanction\w*|legislat\w*|government|tax\w*)\b', text): result.append('Policy')
    if re.search(r'\b(equit\w*|shareholders?|stock market|corporate earnings)\b', text): result.append('Stocks')
    return result


def headline_sentiment(title):
    """Conservative headline-wording labels, not issuer sentiment or price predictions."""
    text = plain(title).lower()
    positive = re.findall(r'\b(?:rise|rises|rising|rose|increase|increases|increased|increasing|gain|gains|gained|growth|recovery|recover|recovers|recovered|improve|improves|improved|improving|surge|surges|surged|strong|stronger)\b', text)
    negative = re.findall(r'\b(?:fall|falls|falling|fell|decline|declines|declined|declining|drop|drops|dropped|dropping|decrease|decreases|decreased|decreasing|weak|weaker|weakness|crisis|disruption|disruptions|shortage|shortages|slump|slumps|slumped)\b', text)
    ambiguous = bool(re.search(r'\b(?:mixed|uncertain|uncertainty|not|no|never|without)\b', text))
    label = 'Neutral' if ambiguous or bool(positive)==bool(negative) else 'Positive' if positive else 'Negative'
    return {'label':label,'method':'headline wording rules','positive_terms':sorted(set(positive)),
            'negative_terms':sorted(set(negative)),'mixed_or_negated':ambiguous}


def parse_feed(content):
    if b'<!doctype' in content.lower() or b'<!entity' in content.lower():
        raise ValueError('Unsupported XML declarations')
    root = ET.fromstring(content)
    items = []
    for node in root.findall('.//item'):
        title = plain(node.findtext('title'))
        url = urljoin('https://www.eia.gov/', (node.findtext('link') or '').strip())
        host = (urlparse(url).hostname or '').lower()
        if urlparse(url).scheme != 'https' or not (host == 'eia.gov' or host.endswith('.eia.gov')):
            continue
        if not title:
            continue
        try:
            published = parsedate_to_datetime(node.findtext('pubDate') or '')
            if published.tzinfo is None: published = published.replace(tzinfo=timezone.utc)
            published = published.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError):
            published = None
        topics = categories(title+' '+plain(node.findtext('description')))
        sentiment = headline_sentiment(title)
        items.append({'id':hashlib.sha256(url.encode()).hexdigest()[:16], 'title':title,
                      'url':url, 'published_at':published, 'source':'U.S. EIA',
                      'categories':topics, 'tag':sentiment['label'], 'sentiment':sentiment})
    return items


def official_news():
    global _news, _news_at, _news_attempt
    with _news_lock:
        now = time.monotonic()
        if _news is not None and now-_news_at < 300:
            return dict(_news, status='partial' if _news.get('feed_failures') else 'ok')
        if _news_attempt and now-_news_attempt < 60:
            return dict(_news,status='stale',error='Feed refresh pending') if _news else {'status':'unavailable','items':[],'error':'EIA feeds unavailable; retry in one minute.'}
        _news_attempt = now
        items, failures = {}, 0
        for url in FEEDS:
            try:
                for item in parse_feed(download(url, 2_000_000)):
                    items[item['url']] = item
            except Exception:
                failures += 1
        if not items:
            return dict(_news,status='stale',error='Could not refresh EIA news feeds.') if _news else {'status':'unavailable','items':[],'error':'Could not load official EIA news feeds.'}
        ordered = sorted(items.values(), key=lambda i:i['published_at'] or '', reverse=True)
        _news = {'items':ordered,'fetched_at':stamp(),'source':'U.S. EIA RSS','feed_failures':failures}
        _news_at = time.monotonic()
        return dict(_news,status='partial' if failures else 'ok')


def news_window(payload, now=None):
    from .news_analysis import filter_news
    return filter_news(payload, now)


@router.get('/api/energy/news')
def news():
    from .global_news import combined_news
    return combined_news()
