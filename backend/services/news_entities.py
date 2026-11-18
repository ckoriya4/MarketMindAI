"""Headline company mentions and descriptive factor/sector relevance, not measured impact."""
import csv
import re
from pathlib import Path

BASE=Path(__file__).resolve().parent.parent
FACTOR_SECTORS={
 'Rates & inflation':['Banking & financial services','Real estate','Auto'],
 'Crude & energy':['Oil & gas','Aviation','Paints & chemicals'],
 'Currency & global economy':['IT services','Pharmaceutical exports','Import/export businesses'],
 'Policy & geopolitics':['Depends on the specific policy and country'],
 'Company & earnings':[], 'Other market news':[],
}

def catalog():
    rows=[]
    for path in (BASE/'nifty50.csv',BASE/'news_companies.csv'):
        if not path.exists():continue
        try:
            with path.open(encoding='utf-8-sig',newline='') as f:
                for row in csv.DictReader(f):
                    symbol=(row.get('Symbol') or '').strip()
                    name=(row.get('Company Name') or row.get('Company') or '').strip()
                    sector=(row.get('Industry') or row.get('Sector') or '').strip()
                    aliases=[a.strip() for a in (row.get('Aliases') or '').split('|') if a.strip()]
                    if symbol or name:rows.append(dict(symbol=symbol,name=name or symbol,sector=sector,aliases=aliases))
        except (OSError,UnicodeError,csv.Error):continue
    return rows

def normalize(text):return re.sub(r'[^a-z0-9]+',' ',text.casefold()).strip()

def match_companies(items, companies):
    found={}
    for item in items:
        title=item.get('title','');text=' '+normalize(title)+' '
        matched=False
        for row in companies:
            terms=[row['symbol'],row['name']]+row.get('aliases',[])
            # Short ordinary words such as IT/LT cannot safely identify a company.
            if any(len(normalize(term))>=3 and ' '+normalize(term)+' ' in text for term in terms):
                found[row['name']]=dict(name=row['name'],symbol=row['symbol'],sector=row['sector'] or 'Unmapped',basis='Headline mention');matched=True
        if not matched:
            # Exchange announcement headings often contain only a legal company name.
            m=re.fullmatch(r'\s*([A-Za-z0-9][A-Za-z0-9 &.,()\-/]{2,110}?\b(?:Limited|Ltd\.?))(?:\s*\([A-Za-z0-9]+\))?\s*',title,re.I)
            if m:
                name=m.group(1).strip();found[name]=dict(name=name,symbol='',sector='Unmapped',basis='Legal name in headline')
    return sorted(found.values(),key=lambda row:row['name'].casefold())

def enrich_factor(name,items,companies):
    mentions=match_companies(items,companies)
    return dict(companies=mentions,
        mentioned_company_sectors=sorted({r['sector'] for r in mentions if r['sector']!='Unmapped'}),
        related_sectors=FACTOR_SECTORS.get(name,[]),
        relevance_note='Related sectors are a broad watchlist, not confirmed impact. Companies are headline mentions only; direction is not inferred for each company.')
