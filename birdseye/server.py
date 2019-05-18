from __future__ import print_function, division, absolute_import

import json
from collections import OrderedDict
from functools import partial
from os.path import basename

from future import standard_library
from littleutils import DecentJSONEncoder, withattrs, group_by_attr

standard_library.install_aliases()

import argparse
import os
import sys

from flask import Flask, request, jsonify, url_for
from flask.templating import render_template
from flask_humanize import Humanize
from werkzeug.routing import PathConverter
import sqlalchemy

from birdseye.db import Database
from birdseye.utils import short_path, IPYTHON_FILE_PATH, fix_abs_path, is_ipython_cell


app = Flask('birdseye')
app.jinja_env.auto_reload = True

Humanize(app)


class FileConverter(PathConverter):
    regex = '.*?'


app.url_map.converters['file'] = FileConverter


db = Database()
Session = db.Session
Function = db.Function
Call = db.Call


@app.route('/')
@db.provide_session
def index(session):
    all_paths = db.all_file_paths()

    recent_calls = (session.query(*(Call.basic_columns + Function.basic_columns))
                        .join(Function)
                        .order_by(Call.start_time.desc())[:100])

    files = OrderedDict()

    for row in recent_calls:
        if is_ipython_cell(row.file):
            continue
        files.setdefault(
            row.file, OrderedDict()
        ).setdefault(
            row.name, row
        )

    for path in all_paths:
        files.setdefault(
            path, OrderedDict()
        )

    short = partial(short_path, all_paths=all_paths)

    return render_template('index.html',
                           short=short,
                           files=files)


@app.route('/file/<file:path>')
@db.provide_session
def file_view(session, path):
    path = fix_abs_path(path)

    # Get all calls and functions in this file
    filtered_calls = (session.query(*(Call.basic_columns + Function.basic_columns))
                      .join(Function)
                      .filter_by(file=path)
                      .subquery('filtered_calls'))

    # Get the latest call *time* for each function in the file
    latest_calls = session.query(
        filtered_calls.c.name,
        sqlalchemy.func.max(filtered_calls.c.start_time).label('maxtime')
    ).group_by(
        filtered_calls.c.name,
    ).subquery('latest_calls')

    # Get the latest call for each function
    query = session.query(filtered_calls).join(
        latest_calls,
        sqlalchemy.and_(
            filtered_calls.c.name == latest_calls.c.name,
            filtered_calls.c.start_time == latest_calls.c.maxtime,
        )
    ).order_by(filtered_calls.c.start_time.desc())
    funcs = group_by_attr(query, 'type')

    # Add any functions which were never called
    all_funcs = sorted(session.query(Function.name, Function.type)
                       .filter_by(file=path)
                       .distinct())
    func_names = {row.name for row in query}
    for func in all_funcs:
        if func.name not in func_names:
            funcs[func.type].append(func)

    return render_template('file.html',
                           funcs=funcs,
                           is_ipython=path == IPYTHON_FILE_PATH,
                           full_path=path,
                           short_path=basename(path))


@app.route('/file/<file:path>/__function__/<func_name>')
@db.provide_session
def func_view(session, path, func_name):
    path = fix_abs_path(path)
    query = get_calls(session, path, func_name, 200)
    if query:
        func = query[0]
        calls = [withattrs(Call(), **row._asdict()) for row in query]
    else:
        func = session.query(Function).filter_by(file=path, name=func_name)[0]
        calls = None

    return render_template('function.html',
                           func=func,
                           short_path=basename(path),
                           calls=calls)


@app.route('/api/file/<file:path>/__function__/<func_name>/latest_call/')
@db.provide_session
def latest_call(session, path, func_name):
    path = fix_abs_path(path)
    call = get_calls(session, path, func_name, 1)[0]
    return jsonify(dict(
        id=call.id,
        url=url_for(call_view.__name__,
                    call_id=call.id),
    ))


def get_calls(session, path, func_name, limit):
    return (session.query(*(Call.basic_columns + Function.basic_columns))
                .join(Function)
                .filter_by(file=path, name=func_name)
                .order_by(Call.start_time.desc())[:limit])


@db.provide_session
def base_call_view(session, call_id, template):
    call = session.query(Call).filter_by(id=call_id).one()
    func = call.function
    return render_template(template,
                           short_path=basename(func.file),
                           call=call,
                           func=func)


@app.route('/call/<call_id>')
def call_view(call_id):
    return base_call_view(call_id, 'call.html')


@app.route('/ipython_call/<call_id>')
def ipython_call_view(call_id):
    return base_call_view(call_id, 'ipython_call.html')


@app.route('/ipython_iframe/<call_id>')
def ipython_iframe_view(call_id):
    """
    This view isn't generally used, it's just an easy way to play with the template
    without a notebook.
    """
    return render_template('ipython_iframe.html',
                           container_id='1234',
                           port=7777,
                           call_id=call_id)


@app.route('/kill', methods=['POST'])
def kill():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    return 'Server shutting down...'


@app.route('/api/call/<call_id>')
@db.provide_session
def api_call_view(session, call_id):
    call = session.query(Call).filter_by(id=call_id).one()
    func = call.function
    return DecentJSONEncoder().encode(dict(
        call=dict(data=call.parsed_data, **Call.basic_dict(call)),
        function=dict(data=func.parsed_data, **Function.basic_dict(func))))


@app.route('/api/calls_by_body_hash/<body_hash>')
@db.provide_session
def calls_by_body_hash(session, body_hash):
    query = (session.query(*Call.basic_columns + (Function.data,))
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
@db.provide_session
def body_hashes_present(session):
    hashes = request.get_json()
    query = (session.query(Function.body_hash, sqlalchemy.func.count(Call.id))
             .outerjoin(Call)
             .filter(Function.body_hash.in_(hashes))
             .group_by(Function.body_hash))
    return DecentJSONEncoder().encode([
        dict(hash=h, count=count)
        for h, count in query
    ])


def main(argv=sys.argv[1:]):
    # Support legacy CLI where there was just one positional argument: the port
    if len(argv) == 1 and argv[0].isdigit():
        argv.insert(0, '--port')

    parser = argparse.ArgumentParser(description="Bird's Eye: A graphical Python debugger")
    parser.add_argument('-p', '--port', help='HTTP port, default is 7777', default=7777, type=int)
    parser.add_argument('--host', help="HTTP host, default is 'localhost'", default='localhost')

    args = parser.parse_args(argv)
    app.run(
        port=args.port,
        host=args.host,
        use_reloader=os.environ.get('BIRDSEYE_RELOADER') == '1',
    )


if __name__ == '__main__':
    main()
