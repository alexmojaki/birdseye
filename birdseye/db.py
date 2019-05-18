from __future__ import print_function, division, absolute_import

import functools
import sys

from future import standard_library
from sqlalchemy.exc import OperationalError, InterfaceError, InternalError, ProgrammingError, ArgumentError

standard_library.install_aliases()
import json
import os
from typing import List
from contextlib import contextmanager

from humanize import naturaltime
from markupsafe import Markup
from sqlalchemy import Sequence, UniqueConstraint, create_engine, Column, Integer, Text, ForeignKey, DateTime, String, \
    Index
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy.orm import backref, relationship, sessionmaker
from sqlalchemy.dialects.mysql import LONGTEXT
from littleutils import select_attrs, retry
from birdseye.utils import IPYTHON_FILE_PATH, is_ipython_cell
from sqlalchemy.dialects.mysql.base import RESERVED_WORDS

RESERVED_WORDS.add('function')

DB_VERSION = 1


class Database(object):
    def __init__(self, db_uri=None, _skip_version_check=False):
        self.db_uri = db_uri = (
                db_uri
                or os.environ.get('BIRDSEYE_DB')
                or os.path.join(os.path.expanduser('~'),
                                '.birdseye.db'))

        kwargs = dict(
            pool_recycle=280,
            echo=False,  # for convenience when debugging
        )

        try:
            engine = create_engine(db_uri, **kwargs)
        except ArgumentError:
            db_uri = 'sqlite:///' + db_uri
            engine = create_engine(db_uri, **kwargs)

        self.engine = engine

        self.Session = sessionmaker(bind=engine)

        class Base(object):
            @declared_attr
            def __tablename__(cls):
                return cls.__name__.lower()

        Base = declarative_base(cls=Base)  # type: ignore

        class KeyValue(Base):
            key = Column(String(50), primary_key=True)
            value = Column(Text)

        db_self = self

        class KeyValueStore(object):
            def __getitem__(self, item):
                with db_self.session_scope() as session:
                    return (session
                            .query(KeyValue.value)
                            .filter_by(key=item)
                            .scalar())

            def __setitem__(self, key, value):
                with db_self.session_scope() as session:
                    session.query(KeyValue).filter_by(key=key).delete()
                    session.add(KeyValue(key=key, value=str(value)))

            __getattr__ = __getitem__
            __setattr__ = __setitem__

        LongText = LONGTEXT if engine.name == 'mysql' else Text

        class Call(Base):
            id = Column(String(length=32), primary_key=True)
            function_id = Column(Integer, ForeignKey('function.id'), index=True)
            function = relationship('Function', backref=backref('calls', lazy='dynamic'))
            arguments = Column(Text)
            return_value = Column(Text)
            exception = Column(Text)
            traceback = Column(Text)
            data = Column(LongText)
            start_time = Column(DateTime, index=True)

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
                    return str(self.return_value)
                else:
                    return str(self.exception)

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
            type = Column(Text)  # function or module
            html_body = Column(LongText)
            lineno = Column(Integer)
            data = Column(LongText)
            hash = Column(String(length=64), index=True)
            body_hash = Column(String(length=64), index=True)

            __table_args__ = (
                UniqueConstraint('hash',
                                 name='everything_unique'),
                Index('idx_file', 'file', mysql_length=256),
                Index('idx_name', 'name', mysql_length=32),
            )

            @property
            def parsed_data(self):
                return json.loads(self.data)

            @staticmethod
            def basic_dict(func):
                return select_attrs(func, 'file name lineno hash body_hash type')

            basic_columns = (file, name, lineno, hash, body_hash, type)

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
            sys.exit('The birdseye database schema is out of date. '
                     'Run "python -m birdseye.clear_db" to delete the existing tables.')

    def table_exists(self, table):
        return self.engine.dialect.has_table(self.engine, table.__name__)

    def all_file_paths(self):
        # type: () -> List[str]
        with self.session_scope() as session:
            paths = [f[0] for f in session.query(self.Function.file).distinct()
                     if not is_ipython_cell(f[0])]
        paths.sort()
        if IPYTHON_FILE_PATH in paths:
            paths.remove(IPYTHON_FILE_PATH)
            paths.insert(0, IPYTHON_FILE_PATH)
        return paths

    def clear(self):
        for model in [self.Call, self.Function, self._KeyValue]:
            if self.table_exists(model):
                model.__table__.drop(self.engine)

    @contextmanager
    def session_scope(self):
        """Provide a transactional scope around a series of operations."""
        session = self.Session()
        try:
            yield session
            session.commit()
        except:
            session.rollback()
            raise
        finally:
            session.close()

    def provide_session(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with self.session_scope() as session:
                return func(session, *args, **kwargs)

        return retry_db(wrapper)


# Based on https://docs.sqlalchemy.org/en/latest/errors.html#error-dbapi
retry_db = retry(3, (InterfaceError, OperationalError, InternalError, ProgrammingError))
