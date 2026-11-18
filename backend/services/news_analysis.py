"""Two IST calendar dates and descriptive headline sentiment shares, not price impact."""
import re
from datetime import datetime, timezone, timedelta

IST=timezone(timedelta(hours=5,minutes=30))
FACTORS={
 'Rates & inflation': r'\b(rate[s]?|inflation|cpi|ppi|fed|rbi|monetary|yield[s]?)\b',
 'Crude & energy': r'\b(oil|crude|brent|wti|opec|gas|energy|petroleum)\b',
 'Company & earnings': r'\b(earnings|profit[s]?|revenue|results|dividend|company|shares|stocks|ipo|merger)\b',
 'Currency & global economy': r'\b(dollar|rupee|forex|currency|gdp|employment|payroll[s]?|jobs|unemployment)\b',
 'Policy & geopolitics': r'\b(sebi|government|policy|tax|tariff[s]?|war|sanction[s]?|trade|regulation|ministry)\b',
}

def bounds(now=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('Timezone-aware now required')
    local=now.astimezone(IST)
    return (local-timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0),now

def in_window(value, now=None):
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.tzinfo is None:return False
        start,end=bounds(now)
        return start<=dt<=end
    except (ValueError,TypeError,AttributeError):return False

def filter_news(payload, now=None):
    start,end=bounds(now)
    items={i['url']:i for i in payload.get('items',[]) if in_window(i.get('published_at'),end)}
    return dict(payload,items=sorted(items.values(),key=lambda i:datetime.fromisoformat(i['published_at'].replace('Z','+00:00')),reverse=True),
        days=2,total=len(items),range_start=start.isoformat(),range_end=end.isoformat(),
        coverage='Today and yesterday IST; only available timestamped publisher headlines.')

def shares(items):
    labels=('Positive','Negative','Neutral')
    counts={label:0 for label in labels}
    for item in items:
        label=(item.get('sentiment') or {}).get('label') or item.get('tag')
        counts[label if label in labels else 'Neutral']+=1
    total=len(items)
    percentages={label:None for label in labels}
    if total:
        # Largest remainders in tenths: displayed numbers always sum to 100.0.
        units={label:counts[label]*1000//total for label in labels}
        for label in sorted(labels,key=lambda l:counts[l]*1000%total,reverse=True)[:1000-sum(units.values())]:units[label]+=1
        percentages={label:units[label]/10 for label in labels}
    direction='Unavailable' if not total else 'Positive' if counts['Positive']>counts['Negative'] else 'Negative' if counts['Negative']>counts['Positive'] else 'Balanced'
    return dict(total=total,counts=counts,percentages=percentages,direction=direction)

def analyze(items):
    from .news_entities import catalog, enrich_factor
    companies=catalog()
    unique={}
    for item in items:
        title=re.sub(r'\W+',' ',item.get('title','').casefold()).strip()
        if title:unique.setdefault(title,item)
    rows=list(unique.values());groups={name:[] for name in FACTORS};groups['Other market news']=[]
    for item in rows:
        matched=False
        for name,pattern in FACTORS.items():
            if re.search(pattern,item['title'],re.I):groups[name].append(item);matched=True
        if not matched:groups['Other market news'].append(item)
    return dict(overall=shares(rows),factors=[dict(name=name,**shares(group),**enrich_factor(name,group,companies)) for name,group in groups.items() if group],
        method='Equal-weight automated headline wording; identical normalized titles counted once. Factors use headline keywords and may overlap.',
        meaning='Percent of classified headlines, not market price impact or probability. Calendar events excluded.',
        available_articles=len(items),unique_headlines=len(rows))
