from __future__ import print_function, division, absolute_import

from future import standard_library

standard_library.install_aliases()
import json
import os

from humanize import naturaltime
from markupsafe import Markup
from sqlalchemy import Sequence, UniqueConstraint, create_engine, Column, Integer, Text, ForeignKey, DateTime, String
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy.orm import backref, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

DB_URI = os.environ.get('BIRDSEYE_DB',
                        'sqlite:///' + os.path.join(os.path.expanduser('~'),
                                                    '.birdseye.db'))

connect_args = {}
if DB_URI.startswith('sqlite'):
    connect_args['check_same_thread'] = False

engine = create_engine(DB_URI,
                       connect_args=connect_args,
                       poolclass=StaticPool)

Session = sessionmaker(bind=engine)
session = Session()


class Base(object):
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()


Base = declarative_base(cls=Base)  # type: ignore


class Call(Base):
    id = Column(String(length=32), primary_key=True)
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
    hash = Column(String(length=64))

    __table_args__ = (UniqueConstraint('hash',
                                       name='everything_unique'),)


Base.metadata.create_all(engine)
