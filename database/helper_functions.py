
from database.xml_keywords import *
import datetime
import logging
import re


module_logger = logging.getLogger('SRA_App.load_db')

def dict2tuplelist(d):
    '''Create a tuple from a dict'''
    return [(k, v) for k, v in d.items()]

def list2str(l):
    '''Create a string from list for neo4j cql'''
    lstr = ', '.join("'{0}'".format(x) for x in l)
    return "[{}]".format(lstr)

def merge_dict(d1, d2):
    '''Function to merge dictionaries'''
    return {**d1, **d2}

def cql_dict2str(d):
    '''Create a cypher from a dictionary'''
    if not d:
        return ""
    cql = []
    cql.append("{")
    i = []
    for k, v in d.items():
        i.append("""`%s`:"%s\"""" % (k, v))
    cql.append(", ".join(i))
    cql.append("}")
    return ''.join(cql)

def cql_create(label, attributes, variable, merge=False):
    '''Cypher constructor to create/merge a node'''
    if not attributes:
        module_logger.warning("""Adding empty attributes for label: {}.
                           This might lead to a match with ever
                           matching label in the db and therefore
                           resulting in a huge db addition.
                           """.format(label))
    tag = xml_MERGE if merge else xml_CREATE
    cql = [tag, "(%s:%s" % (variable, label)]
    if len(attributes.items()) != 0:
        cql.append(cql_dict2str(attributes))
    cql.append(")")
    return " ".join(cql)

def cql_relation(source, relation, goal, merge=False, attributes={}):
    '''Cypher constructor to create/merge a relationship'''
    tag = xml_MERGE if merge else xml_CREATE
    if not attributes:
        return "{} ({})-[:`{}`]->({})".format(tag, source, relation, goal)
    return "{} ({})-[:`{}` {}]->({})".format(tag, source, relation,
                                             cql_dict2str(attributes), goal)

def escape_attrib(attributes):
    '''Escape special character for cypher query language'''
    if isinstance(attributes, (bytes, str)):
        #bug for a literal \ in strings -> escape them separatly
        s = re.sub(r'\\', r'\\\\',attributes)
        #escape " normally - we do not need to escape ' as we wrap it in "
        return re.sub('"', r'\"', s)
    elif isinstance(attributes, list):
      r = []
      for i in attributes:
        r.append(escape_attrib(i))
      return r
    elif isinstance(attributes, dict):
      r = {}
      for k, v in attributes.items():
        r[k] = escape_attrib(v)
      return r
    else:
      try:
        return escape_attrib(str(attributes))
      except Exception as e:
        msg = ("Could not escape the following "
               "attributes:\n%s" % attributes)
        module_logger.error(msg)

def batch(iterable, n=1):
  '''traverse an iterable as batch with size n'''
  l = len(iterable)
  for ndx in range(0, l, n):
    yield iterable[ndx:min(ndx + n, l)]


class CleanDate():
    '''
    Class witch contains to functions to clean dates for neo4j

    Args:
        parent: Used for logger names only

    Attributes:
        month_lookup: lookupdict for month name to month int
    '''
    def __init__(self, parent=None):
        super(CleanDate, self).__init__()
        if not parent:
            self.logger_name = 'CleanDate'
        else:
            self.parent = parent
            self.logger_name = '{}.CleanDate'.format(parent.logger_name)
        self.logger = logging.getLogger(self.logger_name)
        self.month_lookup = {'jan' : 1, 'feb' : 2, 'mar' : 3, 'apr' : 4,
                             'may' : 5, 'june' : 6, 'july' : 7, 'aug' : 8,
                             'sept' : 9, 'oct' : 10, 'nov' : 11, 'dec' : 12,
                             'january' : 1, 'february' : 2, 'march' : 3,
                             'april' : 4, 'august' : 8, 'september' : 9,
                             'october' : 10, 'november' : 11, 'december' : 12,
                             'sep' : 9, 'jun' : 6, 'jul' : 7}

    def fix_year(self, year):
        '''fix a possible year string to an actual year str'''
        #year shold always be an int
        if isinstance(year, str):
            try:
                year = int(year)
            except:
                raise ValueError(f'ValueError: year is not an int: {year}')
        now = datetime.date.today().year
        now_short = str(now)[2:]
        if len(str(year)) == 4:
            if year > now:
                raise ValueError(f'ValueError: year is in the future: {year}')
            if year < 1900:
                raise ValueError('ValueError: year is too '
                                 f'much in the past: {year}')
            return year
        if len(str(year)) == 2:
            now_short = str(now)[2:]
            #assume 20xx if year <= now
            if year <= now_short:
                return int('20'+str(year))
            return int('19'+str(year))
        if len(str(year)) == 1:
            #assume 200x
            return int('200'+str(year))
        raise ValueError(f'ValueError: could not convert year: {year}')

    def fix_month(self, month):
        '''fix a possible month string to an actual month str as int'''
        #see if month is int or str
        if isinstance(month, str):
            if month.isdigit():
                month = int(month)
            else:
                #match single . at end like apr.
                if bool(re.match('[^.]*\.$', month)):
                    month, _ = month.split('.')
                try:
                    month = self.month_lookup[month.lower()]
                except:
                    raise ValueError('ValueError: could not '
                                     f'lookup month: {month}')
        if month > 12 or month <1:
            raise ValueError('ValueError: month is not '
                             f'between 1 and 12: {month}')
        return month

    def fix_day(self, day):
        '''fix a possible day string to an actual day str'''
        if isinstance(day, str):
            try:
                day = int(day)
            except:
                raise ValueError(f'ValueError: day is not an int: {day}')
        if day > 31 or day <1:
            raise ValueError(f'ValueError: day is not between 1 and 31: {day}')
        return day

    def _get_date_m_y(self, date, delim):
        '''fix a date with only month and year from a delimiter'''
        m, y = date.split(delim)
        try:
            day, month, year = 1, self.fix_month(m), self.fix_year(y)
        except:
            try:
                day, month, year = 1, self.fix_month(y), self.fix_year(m)
            except:
                raise ValueError(f'ValueError: could not convert {date}')
        return day, month, year

    def _get_date_d_m_y(self, date, delim):
        '''fix a date with day, month and year from a delimiters'''
        d, m, y = date.split(delim)
        try:
            day, month, year = (self.fix_day(d), self.fix_month(m),
                                self.fix_year(y))
        except:
            try:
                day, month, year = (self.fix_day(m), self.fix_month(d),
                                    self.fix_year(y))
            except:
                try:
                    day, month, year = (self.fix_day(y), self.fix_month(m),
                                        self.fix_year(d))
                except:
                    raise ValueError(f'ValueError: could not convert {date}')
        return day, month, year


    def safe_fix_date(self, date):
        '''catch the error if fix date does raises one'''
        try:
            d = self.fix_date(date)
        except:
            #warning only if some lookup not working. info from fix date itself if
            #it was a string without -, /, or .
            self.logger.warning(f"Could not convert: {date} return 'unknown'")
            d = 'unknown'
        return d


    def fix_date(self, date):
        '''fixes dates to match format yyyy-mm-dd'''
        #matches exactly \w00:00 so it may be a datetime
        if bool(re.match('^[^:]* {1}[0..9]{2}:{1}[0..9]{2}[^:]*$', date)):
            f, t = date.split(':')
            #remove \w and leading numbers
            return  self.fix_date(f[0:-3])
        #matches exactly start00:00\w so it may be a datetime
        elif bool(re.match('^[0..9]{2}:{1}[0..9]{2} {1}[^:]*$', date)):
            f, t = date.split(':')
            #remove \w and leading numbers
            return  self.fix_date(t[3:])
        #matches exactly \w00:00:00 so it may be a datetime with seconds
        elif bool(re.match('^.* {1}\d{2}:\d{2}:\d{2}.*$', date)):
            f, m, t = date.split(':')
            #remove \w and leading numbers
            return  self.fix_date(f[0:-3])
        #matches exactly start00:00:00\w so it may be a datetime with seconds
        elif bool(re.match('^\d{2}:\d{2}:\d{2} {1}.*$', date)):
            f, m, t = date.split(':')
            #remove \w and leading numbers
            return  self.fix_date(t[3:])
        #matches exactly 1 / in date
        elif bool(re.match('^[^\/]*\/{1}[^\/]*$', date)):
            f, t = date.split('/')
            #if len of first and last chars match assume it is something like
            #fromDate/toDate - take only second date
            if len(f) == len(t):
                return self.fix_date(t)
            #if they do not match it is most likely a date with /
            #as only one / assume month/year or year/month
            day, month, year = self._get_date_m_y(date, '/')
        #match exactly 2 / in date assume format day/month/year or month/day/year or year/month/day
        elif bool(re.match('^[^\/]*\/{1}[^\/]*\/{1}[^\/]*$', date)):
            day, month, year = self._get_date_d_m_y(date, '/')
        #match exactly 1 - in date assume format month-year or year-month
        elif bool(re.match('^[^-]*-{1}[^-]*$', date)):
            day, month, year = self._get_date_m_y(date, '-')
        #match exactly 2 - in date assume format day-month-year or year-month-day
        elif bool(re.match('^[^-]*-{1}[^-]*-{1}[^-]*$', date)):
            day, month, year = self._get_date_d_m_y(date, '-')
        #match exactly 1 . in date assume format month.year or year.month
        elif bool(re.match('^[^.]*\.{1}[^.]*$', date)):
            day, month, year = self._get_date_m_y(date, '.')
        #match exactly 2 . in date assume format day-month-year or year-month-day
        elif bool(re.match('^[^.]*\.{1}[^.]*.{1}[^.]*$', date)):
            day, month, year = self._get_date_d_m_y(date, '.')
        #assume only year as no delimiters are set
        else:
            if isinstance(date, str):
                if date.isdigit():
                    day, month, year = 1, 1, self.fix_year(date)
                else:
                    self.logger.info(f"Could not convert: {date} return 'unknown'")
                    return 'unknown'
        return f'{year}-{month:02d}-{day:02d}'