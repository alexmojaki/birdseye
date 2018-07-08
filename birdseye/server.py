from __future__ import print_function, division, absolute_import

import json

from future import standard_library
from littleutils import DecentJSONEncoder, withattrs

standard_library.install_aliases()

import argparse
import os
import sys

from flask import Flask, request
from flask.templating import render_template
from flask_humanize import Humanize
from werkzeug.routing import PathConverter
import sqlalchemy

from birdseye.db import Database
from birdseye.utils import short_path, IPYTHON_FILE_PATH


app = Flask('birdseye')
Humanize(app)


class FileConverter(PathConverter):
    regex = '.*?'


app.url_map.converters['file'] = FileConverter


db = Database()
Session = db.Session
Function = db.Function
Call = db.Call


@app.route('/')
def index():
    files = db.all_file_paths()
    files = zip(files, [short_path(f, files) for f in files])
    return render_template('index.html',
                           files=files)


@app.route('/file/<file:path>')
def file_view(path):
    return render_template('file.html',
                           funcs=sorted(Session().query(Function.name).filter_by(file=path).distinct()),
                           is_ipython=path == IPYTHON_FILE_PATH,
                           full_path=path,
                           short_path=short_path(path, db.all_file_paths()))


@app.route('/file/<file:path>/function/<func_name>')
def func_view(path, func_name):
    session = Session()
    query = (session.query(*(Call.basic_columns + Function.basic_columns))
                 .join(Function)
                 .filter_by(file=path, name=func_name)
                 .order_by(Call.start_time.desc())[:200])
    if query:
        func = query[0]
        calls = [withattrs(Call(), **row._asdict()) for row in query]
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


@app.route('/api/call/<call_id>')
def api_call_view(call_id):
    call = Session().query(Call).filter_by(id=call_id).one()
    func = call.function
    return DecentJSONEncoder().encode(dict(
        call=dict(data=call.parsed_data, **Call.basic_dict(call)),
        function=dict(data=func.parsed_data, **Function.basic_dict(func))))


@app.route('/api/calls_by_body_hash/<body_hash>')
def calls_by_body_hash(body_hash):
    query = (Session().query(*Call.basic_columns + (Function.data,))
                 .join(Function)
                 .filter_by(body_hash=body_hash)
                 .order_by(Call.start_time.desc())[:200])

    calls = [Call.basic_dict(withattrs(Call(), **row._asdict()))
             for row in query]

    function_data_set = {row.data for row in query}
    ranges = set()
    loop_ranges = set()
    for function_data in function_data_set:
        function_data = json.loads(function_data)

        def add(key, ranges_set):
            for node in function_data[key]:
                ranges_set.add((node['start'], node['end']))

        add('node_ranges', ranges)

        # All functions are expected to have the same set
        # of loop nodes
        current_loop_ranges = set()
        add('loop_ranges', current_loop_ranges)
        assert loop_ranges in (set(), current_loop_ranges)
        loop_ranges = current_loop_ranges

    ranges = [dict(start=start, end=end) for start, end in ranges]
    loop_ranges = [dict(start=start, end=end) for start, end in loop_ranges]

    return DecentJSONEncoder().encode(dict(
        calls=calls, ranges=ranges, loop_ranges=loop_ranges))


@app.route('/api/body_hashes_present/', methods=['POST'])
def body_hashes_present():
    hashes = request.json
    query = (Session().query(Function.body_hash, sqlalchemy.func.count(Call.id))
             .outerjoin(Call)
             .filter(Function.body_hash.in_(hashes))
             .group_by(Function.body_hash))
    return DecentJSONEncoder().encode([
        dict(hash=h, count=count)
        for h, count in query
    ])


def main():
    # Support legacy CLI where there was just one positional argument: the port
    if len(sys.argv) == 2 and sys.argv[1].isdigit():
        sys.argv.insert(1, '--port')

    parser = argparse.ArgumentParser(description="Bird's Eye: A graphical Python debugger")
    parser.add_argument('-p', '--port', help='HTTP port, default is 7777', default=7777, type=int)
    parser.add_argument('--host', help="HTTP host, default is 'localhost'", default='localhost')

    args = parser.parse_args()
    app.run(
        debug=True,
        port=args.port,
        host=args.host,
        use_reloader=os.environ.get('BIRDSEYE_RELOADER') == '1',
    )


if __name__ == '__main__':
    main()
