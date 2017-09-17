import json
import os

from humanize import naturaltime
from markupsafe import Markup
from sqlalchemy import Sequence, UniqueConstraint, create_engine, Column, Integer, Text, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy.orm import backref, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from birdseye.utils import Consumer

DB_URI = os.environ.get('BIRDSEYE_DB',
                        'sqlite:///' + os.path.join(os.path.expanduser('~'),
                                                    '.birdseye.db'))

if os.environ.get('BIRDSEYE_TESTING_IN_MEMORY'):
    engine_kwargs = dict(connect_args={'check_same_thread': False},
                         poolclass=StaticPool)
else:
    engine_kwargs = {}

engine = create_engine(DB_URI, **engine_kwargs)

Session = sessionmaker(bind=engine)
session = Session()
db_consumer = Consumer()


class Base(object):
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()


Base = declarative_base(cls=Base)


class Call(Base):
    id = Column(Text(length=32), primary_key=True)
    function_id = Column(Integer, ForeignKey('function.id'))
    function = relationship('Function', backref=backref('calls', lazy='dynamic'))
    arguments = Column(Text)
    return_value = Column(Text)
    exception = Column(Text)
    traceback = Column(Text)
    data = Column(Text)
    start_time = Column(DateTime)

    @property
    def pretty_start_time(self):
        return self._pretty_time(self.start_time)

    @staticmethod
    def _pretty_time(dt):
        if not dt:
            return ''
        return Markup('%s (%s)' % (
            dt.strftime('%Y-%m-%d&nbsp;%H:%M:%S'),
            naturaltime(dt)))

    @property
    def state_icon(self):
        return Markup('<span class="glyphicon glyphicon-%s" '
                      'style="color: %s"></span>' % (
                          ('ok', 'green') if self.success else
                          ('remove', 'red')))

    @property
    def success(self):
        if self.exception:
            assert self.traceback
            assert self.return_value == 'None'
            return False
        else:
            assert not self.traceback
            return True

    @property
    def result(self):
        if self.success:
            return self.return_value
        else:
            return self.exception

    @property
    def arguments_list(self):
        return json.loads(self.arguments)


class Function(Base):
    id = Column(Integer, Sequence('function_id_seq'), primary_key=True)
    file = Column(Text)
    name = Column(Text)
    html_body = Column(Text)
    lineno = Column(Integer)
    data = Column(Text)

    __table_args__ = (UniqueConstraint('file', 'name', 'html_body', 'lineno', 'data',
                                       name='everything_unique'),)


Base.metadata.create_all(engine)
