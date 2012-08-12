try:
  from xml.etree import ElementTree
except ImportError:
  from elementtree import ElementTree

from lxml import etree

import gdata.calendar.data
import gdata.calendar.client
import gdata.acl.data
import atom.data
import iso8601
from jinja2 import Environment
from jinja2 import Template
from jinja2 import FileSystemLoader
import codecs
import time
import datetime
from collections import defaultdict
import UserDict
import sys

COLOUR_MAP = 'colourMap'
COLOUR = 'colour'
LOCATION = 'location'
CALENDAR_MAIN = 'gcalatex'
GOOGLE_EVENTS = 'googleEvents'
FEED_URI = 'feed_uri'
COLUMN_MAP = 'columnMap'
COLUMN_MAP_ID = 'columnMap'
XPOS = 'xpos'
WIDTH = 'width'
ID = 'id'
TITLE = 'title'
AUTHORS = 'authors'
START = 'start'

COLUMN_EXCEPTION = 'column_exception'
TALK_EXCEPTION = 'talk_exception'
NEW_AUTHORS = 'new_authors'

MIN_DUR = 'min_dur'
MAX_LENGTH = 'max_length'

class EventsProvider(object):
    pass

class Event(object):
    
    def __init__(self, title, start, end, where):
        self.title = title
        self.start = start
        self.end = end
        self.where = where
        self.width = None
        self.column = None

class SessionEvent(Event):
    def __init__(self, title, start, end, where, talks):
        super(SessionEvent, self).__init__(title, start, end, where)
        self.talks = talks    

class GoogleEventsProvider(EventsProvider):

    @classmethod
    def tex_escape(cls, s):
        if not s:
            return ''
        return s.replace('&','\\&').replace('\n\n','\\\\').replace('\n','\\\\')

        
    @classmethod
    def parse_date(cls, d):
        ret = iso8601.parse_date(d)
        return ret  
        
    @classmethod
    def get_event(cls, e): 
        title=GoogleEventsProvider.tex_escape(e.title.text)
        start=GoogleEventsProvider.parse_date(e.when[0].start)
        end=GoogleEventsProvider.parse_date(e.when[0].end)
        where=e.where[0].value     
        if e.content.text:
            # This is a session event, we find the individual talks
            talksS = [map(GoogleEventsProvider.tex_escape, t.split('\n'))
                for t in e.content.text.split('\n\n')]
            # Check if the description describes talks
            if not filter(lambda x:len(x) != 2, talksS):
                i = 0
                talks = []
                delta = (end - start)/len(talksS)
                for t in talksS:
                    talks.append({TITLE:t[0],AUTHORS:t[1],START:start+i* delta})
                    i += 1
                    
                return SessionEvent(
                   title=title, start=start, end=end, where=where,
                   talks=talks)
        return Event(
            title=title, start=start, end=end, where=where)
              
    
    def __init__(self, feed_uri):
         self.feed_uri = feed_uri.replace('basic', 'full?max-results=999999')
         calendar_client = gdata.calendar.client.CalendarClient()
         feed = calendar_client.GetCalendarEventFeed(uri=self.feed_uri)
         events = [GoogleEventsProvider.get_event(f) for f in feed.entry]
         self.events = sorted(events, key=lambda e:(e.start, e.title))
         
         
    def get_events(self):
        return self.events
         
                  

class XMLEventsProvider(EventsProvider):
    pass

class EventException(object):

    def match(self, e):
        return None

    def modify(self, e):
        pass

    # Returns True if the exception matches the event
    # and modifies the event object
    def apply_to_event(self, e):
        if self.match(e):
            self.modify(e)
            return True
        return False

class ColumnException(EventException):

    def __init__(self, title, new_layout):
        self.title = title
        self.new_layout = new_layout

    def match(self, e):
        return e.title == self.title

    def modify(self, e):
        e.width = float(self.new_layout[1])
        e.column = float(self.new_layout[0])


class TalkException(EventException):

    def __init__(self, title, new_authors):
        self.title = title
        self.new_authors = new_authors

    def match(self, e):
        if isinstance(e, SessionEvent):
            for talk in e.talks:
                if talk.get(TITLE) == self.title:
                    return True
        return False
        
    def modify(self, e):
        for talk in e.talks:
            if talk.get(TITLE) == self.title:
                talk[AUTHORS] = self.new_authors

    def __str__(self):
        return "Change authors in " + self.title + " to " + self.new_authors

class ColumnMap(object):
    
    def __init__(self, cm):
        self.column_map = dict(
             [(s.get(LOCATION),(s.get(XPOS), s.get(WIDTH))) 
                for s in cm.findall('set')]) 
        self.exceptions = []
        for e in cm.findall(COLUMN_EXCEPTION):
            self.exceptions.append(
                ColumnException(e.get(TITLE),
                                (e.get(XPOS), e.get(WIDTH))))
        for e in cm.findall(TALK_EXCEPTION):
            transformation = TalkException(e.get(TITLE), e.get(NEW_AUTHORS))
            print "Talk transformation", str(transformation)
            self.exceptions.append(transformation)
        self.min_dur = float(cm.get(MIN_DUR) or '0')
        if cm.get(MAX_LENGTH):
            self.max_length = int(cm.get(MAX_LENGTH))
            print MAX_LENGTH, "is", self.max_length
        else:
            self.max_length = None
                           
        
    def get(self, location):
        return self.column_map.get(location)
    



class ColourMap(object):
    
    @classmethod
    def create_map(cls, e):
        if e is not None:
            return ColourMap(dict([(s.get(LOCATION), s.get(COLOUR)) for s in e]))
        # Returns default colour map
        else:
            return dict()
        
    def __init__(self, d):
        self.d = d
        
        
    def get(self, key):       
        return self.d.get(key, 'color1')
        


def get_date(e):
    return datetime.date(year=int(e.get('year')),
        month=int(e.get('month')),day=int(e.get('day')))

def get_time(e):
    return datetime.time(hour=int(e.get('hour') or '0'),
        minute=int(e.get('minute') or '0'),second=int(e.get('second') or '0'))


class CalendarEnvironment(object):
    
    def __init__(self, input_file):
        self.input_file = input_file
        
    def collect_column_maps(self):
        self.column_maps = {} 
        for map in self.tree.findall(COLUMN_MAP):
            self.column_maps[map.get(ID)] = ColumnMap(map)
            
    def parse_input(self):
        fp = codecs.open(self.input_file, mode='r', encoding="utf-8")
        # Gets the main xml tree
        self.tree = etree.parse(fp)
        # Creates the colour map
        self.colour_map = ColourMap.create_map(self.tree.find(COLOUR_MAP))
        # Retreives events from Google if specified
        if self.tree.find(GOOGLE_EVENTS) is not None:   
            print "Found google events"        
            self.events_provider = GoogleEventsProvider(self.tree.find(GOOGLE_EVENTS).get(FEED_URI))
        # Otherwise looks for local events
        # TODO add this
        
        self.collect_column_maps()
                
        for calendar in self.tree.findall('calendar'):
            Calendar(calendar, self.events_provider, self.column_maps, self.colour_map)        

            

class Calendar(object):
    
    def __init__(self, calendar, events_provider, column_maps, colour_map):        
        self.max_hour = 20
        self.min_hour = 7.75
        self.min_dur = None
        self.max_length = None
    
        start_date = get_date(calendar.find('start'))
        end_date = get_date(calendar.find('end'))
        output = calendar.get('output')
        
        print "Rendering calendar from", start_date, "to", end_date, \
                "into", output           


        column_map = column_maps.get(calendar.get(COLUMN_MAP_ID))

        self.daytitle = True
        if calendar.get('daytitle') == 'False':
            self.daytitle = False


        self.min_time = get_time(calendar.find('minTime'))
        self.min_hour = self.min_time.hour + self.min_time.minute/60.0
        self.max_time = get_time(calendar.find('maxTime'))
        self.max_hour = self.max_time.hour + self.max_time.minute/60.0
    
        self.processCalendarDays(events_provider.get_events(), [(start_date, end_date, output)],
            colour_map, column_map=column_map)        


    def assign_columns_to_rooms(self, days, column_map, colour_map):
        ncols = len(set(filter(lambda x:x!=0,column_map.column_map.values())))
        for (d, es) in days:
            for e in es:
                e.color = colour_map.get(e.where)
                column = column_map.get(e.where)
                if column:
                    e.width = float(column[1])
                    e.column = float(column[0])
                for exception in column_map.exceptions:
                    exception.apply_to_event(e)
    
    
    def processCalendarDays(self, events, day_ranges, colour_map, column_map=None, session_titles=True, session_bars=True,
        column_titles=None, column_colors=None,daytitle = True, template='calendar.temp'):
        
        
        for (start_day, end_day, filename) in day_ranges:
            
            
            days = defaultdict(list)
            for e in events:
                day = e.start.date()
                if day >= start_day and day <= end_day:
                    days[day].append(e)
                    
            days = sorted(days.items(), key=lambda t:t[0])
           
    
            
    
            if column_map:
                # remove rooms not in the map first
                days = map(
                    lambda d:
                    (d[0], filter(
                        lambda x:
                        column_map.get(x.where) is not None,
                        d[1]
                        ))
                , days)
                self.assign_columns_to_rooms(days, column_map, colour_map)
                
            s = env.get_template(template).render(
                days=days,min_hour=self.min_hour, max_hour=self.max_hour, session_titles=session_titles,
                column_titles = column_titles,
                column_colors=column_colors,daytitle=self.daytitle,
                min_dur = column_map.min_dur, max_length = column_map.max_length,
                session_bars=session_bars)
            f = codecs.open(filename, 'w',encoding='utf-8')
            f.write(s)
            f.close()
    



def parseDate(s):
    return datetime.datetime.strptime(s.split('T')[0],'%Y-%m-%d').date()

env = Environment(loader=FileSystemLoader('templates'))


inputXML = sys.argv[1]

CalendarEnvironment(inputXML).parse_input()
