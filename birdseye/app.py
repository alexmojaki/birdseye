import json
import os

from flask import Flask
from flask_humanize import Humanize
from flask_sqlalchemy import SQLAlchemy
from humanize import naturaltime
from markupsafe import Markup
from sqlalchemy import Sequence, UniqueConstraint

app = Flask('birdseye')
app.config.update(dict(
    SQLALCHEMY_DATABASE_URI=os.environ.get('BIRDSEYE_DB',
                                           'sqlite:///' + os.path.join(os.path.expanduser('~'),
                                                                       '.birdseye.db')),
    SQLALCHEMY_TRACK_MODIFICATIONS=False),
)
db = SQLAlchemy(app)
Humanize(app)


class Call(db.Model):
    id = db.Column(db.Integer, Sequence('call_id_seq'), primary_key=True)
    function_id = db.Column(db.Integer, db.ForeignKey('function.id'))
    function = db.relationship('Function', backref=db.backref('calls', lazy='dynamic'))
    arguments = db.Column(db.Text)
    return_value = db.Column(db.Text)
    exception = db.Column(db.Text)
    traceback = db.Column(db.Text)
    data = db.Column(db.Text)
    start_time = db.Column(db.DateTime)

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


class Function(db.Model):
    id = db.Column(db.Integer, Sequence('function_id_seq'), primary_key=True)
    file = db.Column(db.Text)
    name = db.Column(db.Text)
    html_body = db.Column(db.Text)
    lineno = db.Column(db.Integer)
    data = db.Column(db.Text)

    __table_args__ = (UniqueConstraint('file', 'name', 'html_body', 'lineno', 'data',
                                       name='everything_unique'),)


db.create_all()
