from __future__ import print_function, division, absolute_import

from future import standard_library

standard_library.install_aliases()
import sys

from flask import Flask, request
from flask.templating import render_template
from flask_humanize import Humanize
from werkzeug.routing import PathConverter

from birdseye.db import Call, Function, Session
from birdseye.utils import all_file_paths, short_path

app = Flask('birdseye')
Humanize(app)


class FileConverter(PathConverter):
    regex = '.*?'


app.url_map.converters['file'] = FileConverter


@app.route('/')
def index():
    files = sorted(all_file_paths())
    files = zip(files, [short_path(f, files) for f in files])
    return render_template('index.html',
                           files=files)


@app.route('/file/<file:path>')
def file_view(path):
    return render_template('file.html',
                           funcs=sorted(Session().query(Function.name).filter_by(file=path).distinct()),
                           full_path=path,
                           short_path=short_path(path))


@app.route('/file/<file:path>/function/<func_name>')
def func_view(path, func_name):
    session = Session()
    query = (session.query(Call, Function)
             .join(Function)
             .filter_by(file=path, name=func_name)
             .order_by(Call.start_time.desc())
             [:200])
    if query:
        func = query[0][1]
        calls = [p[0] for p in query]
    else:
        func = session.query(Function).filter_by(file=path, name=func_name)[0]
        calls = None

    return render_template('function.html',
                           func=func,
                           calls=calls)


@app.route('/call/<call_id>')
def call_view(call_id):
    call = Session().query(Call).filter_by(id=call_id).one()
    func = call.function
    return render_template('call.html',
                           call=call,
                           func=func)


@app.route('/kill', methods=['POST'])
def kill():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    return 'Server shutting down...'


def main():
    try:
        port = int(sys.argv[1])
    except IndexError:
        port = 7777

    app.run(debug=True, port=port)


if __name__ == '__main__':
    main()
