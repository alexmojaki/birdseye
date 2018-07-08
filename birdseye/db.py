from __future__ import print_function, division, absolute_import

from future import standard_library

standard_library.install_aliases()
import json
import os
from typing import List

from humanize import naturaltime
from markupsafe import Markup
from sqlalchemy import Sequence, UniqueConstraint, create_engine, Column, Integer, Text, ForeignKey, DateTime, String
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy.orm import backref, relationship, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects.mysql import LONGTEXT
from littleutils import select_attrs
from birdseye.utils import IPYTHON_FILE_PATH

DB_VERSION = 0


class Database(object):
    def __init__(self, db_uri=None, _skip_version_check=False):
        self.db_uri = db_uri = (
                db_uri
                or os.environ.get('BIRDSEYE_DB')
                or 'sqlite:///' + os.path.join(os.path.expanduser('~'),
                                               '.birdseye.db'))

        connect_args = {}
        if db_uri.startswith('sqlite'):
            connect_args['check_same_thread'] = False

        self.engine = engine = create_engine(
            db_uri,
            connect_args=connect_args,
            poolclass=StaticPool,
            echo=False)

        self.Session = sessionmaker(bind=engine)
        self.session = session = self.Session()

        class Base(object):
            @declared_attr
            def __tablename__(cls):
                return cls.__name__.lower()

        Base = declarative_base(cls=Base)  # type: ignore

        class KeyValue(Base):
            key = Column(String(50), primary_key=True)
            value = Column(Text)

        class KeyValueStore(object):
            def __getitem__(self, item):
                return (session
                        .query(KeyValue.value)
                        .filter_by(key=item)
                        .scalar())

            def __setitem__(self, key, value):
                session.query(KeyValue).filter_by(key=key).delete()
                session.add(KeyValue(key=key, value=str(value)))
                session.commit()

            __getattr__ = __getitem__
            __setattr__ = __setitem__

        LongText = LONGTEXT if engine.name == 'mysql' else Text

        class Call(Base):
            id = Column(String(length=32), primary_key=True)
            function_id = Column(Integer, ForeignKey('function.id'))
            function = relationship('Function', backref=backref('calls', lazy='dynamic'))
            arguments = Column(Text)
            return_value = Column(Text)
            exception = Column(Text)
            traceback = Column(Text)
            data = Column(LongText)
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

            @property
            def parsed_data(self):
                return json.loads(self.data)

            @staticmethod
            def basic_dict(call):
                return dict(arguments=call.arguments_list,
                            **select_attrs(call, 'id function_id return_value traceback '
                                                 'exception start_time'))

            basic_columns = (id, function_id, return_value,
                             traceback, exception, start_time, arguments)

        class Function(Base):
            id = Column(Integer, Sequence('function_id_seq'), primary_key=True)
            file = Column(Text)
            name = Column(Text)
            html_body = Column(LongText)
            lineno = Column(Integer)
            data = Column(LongText)
            hash = Column(String(length=64))
            body_hash = Column(String(length=64))

            __table_args__ = (UniqueConstraint('hash',
                                               name='everything_unique'),)

            @property
            def parsed_data(self):
                return json.loads(self.data)

            @staticmethod
            def basic_dict(func):
                return select_attrs(func, 'file name lineno hash body_hash')

            basic_columns = (file, name, lineno, hash, body_hash)

        self.Call = Call
        self.Function = Function
        self._KeyValue = KeyValue

        self.key_value_store = kv = KeyValueStore()

        if _skip_version_check:
            return

        if not self.table_exists(Function):
            Base.metadata.create_all(engine)
            kv.version = DB_VERSION
        elif not self.table_exists(KeyValue) or int(kv.version) < DB_VERSION:
            raise ValueError('The birdseye database schema is out of date. '
                             'Run "python -m birdseye.clear_db" to delete the existing tables.')

    def table_exists(self, table):
        return self.engine.dialect.has_table(self.engine, table.__name__)

    def all_file_paths(self):
        # type: () -> List[str]
        paths = [f[0] for f in self.Session().query(self.Function.file).distinct()]
        paths.sort()
        if IPYTHON_FILE_PATH in paths:
            paths.remove(IPYTHON_FILE_PATH)
            paths.insert(0, IPYTHON_FILE_PATH)
        return paths

    def clear(self):
        for model in [self.Call, self.Function, self._KeyValue]:
            if self.table_exists(model):
                model.__table__.drop(self.engine)
