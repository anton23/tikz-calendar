import atom.data
import codecs
from collections import defaultdict
import datetime
import gdata.calendar.data
import gdata.calendar.client
import gdata.acl.data
import iso8601
from jinja2 import Environment
from jinja2 import Template
from jinja2 import FileSystemLoader
from lxml import etree
import os
import sys
import time
import UserDict

LOCATION = 'location'
CALENDAR_MAIN = 'TikZCalendar'
XPOS = 'xpos'
WIDTH = 'width'
ID = 'id'
TITLE = 'title'
AUTHORS = 'authors'
START = 'start'
END = 'end'
OUTPUT = 'output'


def to_field_name(name):
    return name[0].lower() + name[1:]

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


class GoogleEvents(EventsProvider):
    NAME = 'GoogleEvents'
    FEED_URI = 'feed_uri'

    @classmethod
    def create(cls, tree):
        return GoogleEvents(tree.find(cls.NAME).get(cls.FEED_URI))

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
        title=GoogleEvents.tex_escape(e.title.text)
        start=GoogleEvents.parse_date(e.when[0].start)
        end=GoogleEvents.parse_date(e.when[0].end)
        where=e.where[0].value     
        if e.content.text:
            # This is a session event, we find the individual talks
            talksS = [map(GoogleEvents.tex_escape, t.split('\n'))
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
         events = [GoogleEvents.get_event(f) for f in feed.entry]
         print "  Found", len(events), "events"
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

    NAME = 'ColumnException'
    TITLE = 'title'
    XPOS = 'xpos'
    WIDTH = 'width'

    @classmethod
    def create(cls, e):
        return ColumnException(e.get(cls.TITLE),
                                (e.get(cls.XPOS), e.get(cls.WIDTH)))

    def __init__(self, title, new_layout):
        self.title = title
        self.new_layout = new_layout

    def match(self, e):
        return e.title == self.title

    def modify(self, e):
        e.width = float(self.new_layout[1])
        e.column = float(self.new_layout[0])

    def __str__(self):
        return "For event with title \""+ self.title + \
               "\" change column to " + self.new_layout[0] + \
               " and width to " + self.new_layout[1]
    

class TalkException(EventException):

    NAME = 'TalkException'
    TITLE = 'title'
    NEW_AUTHORS = 'new_authors'

    @classmethod
    def create(cls, e):
        return TalkException(e.get(cls.TITLE), e.get(cls.NEW_AUTHORS))

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

    NAME = 'ColumnMap'
    MIN_DUR = 'min_dur'
    MAX_LENGTH = 'max_length'
    TITLE = 'title'
    COLUMN = 'column'
    COLOUR = 'colour'
    
    def __init__(self, cm):
        print "Processing", ColumnMap.NAME, "with ID", cm.get(ID)
        self.column_map = dict(
             [(s.get(LOCATION),(s.get(XPOS), s.get(WIDTH))) 
                for s in cm.findall('set')]) 
        self.exceptions = []
        for e in cm.findall(ColumnException.NAME):
            exp = ColumnException.create(e)
            self.exceptions.append(exp)
            print "  Column exception:", str(exp)
        for e in cm.findall(TalkException.NAME):
            transformation = TalkException.create(e)
            print "  Talk transformation:", str(transformation)
            self.exceptions.append(transformation)
        self.min_dur = float(cm.get(ColumnMap.MIN_DUR) or '0')
        if cm.get(ColumnMap.MAX_LENGTH):
            self.max_length = int(cm.get(ColumnMap.MAX_LENGTH))
            print "  " + ColumnMap.MAX_LENGTH, "is", self.max_length
        else:
            self.max_length = None

        self.column_titles=[]
        for ct in cm.findall(ColumnMap.COLUMN):
            self.column_titles.append({
                    ColumnMap.TITLE:ct.get(ColumnMap.TITLE),
                    XPOS:float(ct.get(XPOS)),
                    WIDTH:float(ct.get(WIDTH)),
                    ColumnMap.COLOUR:ct.get(ColumnMap.COLOUR)
                }
            )
            
                           
    def get(self, location):
        return self.column_map.get(location)
    

class ColourMap(object):
   
    NAME = 'ColourMap'
    COLOUR = 'colour'
    LOCATION = 'location'

    @classmethod
    def create_map(cls, e):
        if e is not None:
            return ColourMap(dict([(s.get(ColourMap.LOCATION), s.get(ColourMap.COLOUR)) for s in e]))
        # Returns default colour map
        else:
            print "No", ColourMap.NAME, "defined!"
            return dict()
        
    def __init__(self, d):
        self.d = d      
        
    def get(self, key):       
        return self.d.get(key, 'color1')


class CalendarEnvironment(object):
    
    def __init__(self, input_file):
        self.input_file = input_file
        self.env = Environment(loader=FileSystemLoader('templates'))
        
    def collect_column_maps(self):
        self.column_maps = {} 
        for map in self.tree.findall(ColumnMap.NAME):
            self.column_maps[map.get(ID)] = ColumnMap(map)
        print "Found", len(self.column_maps), "column maps"
            
    def parse_input(self):
        fp = codecs.open(self.input_file, mode='r', encoding="utf-8")
        # Gets the main xml tree
        self.tree = etree.parse(fp)
        # Creates the colour map
        self.colour_map = ColourMap.create_map(self.tree.find(ColourMap.NAME))
        # Retreives events from Google if specified
        if self.tree.find(GoogleEvents.NAME) is not None:   
            print "Found google events"        
            self.events_provider = GoogleEvents.create(self.tree)
        # Otherwise looks for local events
        # TODO add this
        
        self.collect_column_maps()
                
        for calendar in self.tree.findall(Calendar.NAME):
            Calendar(calendar, self.events_provider, self.column_maps, self.colour_map, self.env)        

            
class Calendar(object):

    NAME = 'Calendar'
    COLUMN_MAP_NAME = to_field_name(ColumnMap.NAME)
    MIN_TIME = 'minTime'
    MAX_TIME = 'maxTime'
    SESSION_TITLES = 'sessionTitles'

    @classmethod
    def get_time(cls, e):
        return datetime.time(hour=int(e.get('hour') or '0'),
            minute=int(e.get('minute') or '0'),second=int(e.get('second') or '0'))

    @classmethod
    def get_date(cls, e):
        return datetime.date(year=int(e.get('year')),
            month=int(e.get('month')),day=int(e.get('day')))


    def __init__(self, calendar, events_provider, column_maps, colour_map, env):        
        self.env = env
        self.max_hour = 20
        self.min_hour = 7.75
        self.min_dur = None
        self.max_length = None
    
        start_date = Calendar.get_date(calendar.find(START))
        end_date = Calendar.get_date(calendar.find(END))
        output = calendar.get(OUTPUT)
        
        print "Rendering calendar from", start_date, "to", end_date, \
                "into", output           

        column_map = column_maps.get(calendar.get(Calendar.COLUMN_MAP_NAME))
        if column_map is None:
            print "Warning, calendar without a column map"

        self.daytitle = True
        if calendar.get('daytitle') == 'False':
            self.daytitle = False

        self.session_titles = True
        if calendar.get(Calendar.SESSION_TITLES) == 'False':
            self.session_titles = False



        self.min_time = Calendar.get_time(calendar.find(Calendar.MIN_TIME))
        self.min_hour = self.min_time.hour + self.min_time.minute/60.0
        self.max_time = Calendar.get_time(calendar.find(Calendar.MAX_TIME))
        self.max_hour = self.max_time.hour + self.max_time.minute/60.0

    
        self.process_calendar_days(events_provider.get_events(), [(start_date, end_date, output)],
            colour_map, column_map=column_map,
            session_titles=self.session_titles,
            column_titles=column_map.column_titles)        


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
    
    
    def process_calendar_days(self, events, day_ranges, colour_map, column_map=None, session_titles=True, session_bars=True,
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
                print "  Total number of events:", sum([len(d[1]) for d in days])
                
            s = self.env.get_template(template).render(
                days=days,min_hour=self.min_hour, max_hour=self.max_hour, session_titles=session_titles,
                column_titles = column_titles,
                column_colors=column_colors,daytitle=self.daytitle,
                min_dur = column_map.min_dur, max_length = column_map.max_length,
                session_bars=session_bars)
            directory = '/'.join(filename.split('/')[:-1])
            if directory and not os.path.exists(directory):
                os.makedirs(directory)
            f = codecs.open(filename, 'w',encoding='utf-8')
            f.write(s)
            f.close()



def main():
    inputXML = sys.argv[1]
    CalendarEnvironment(inputXML).parse_input()

if __name__ == '__main__':main()
