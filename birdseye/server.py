import os

from flask.templating import render_template

from birdseye.app import app, Call, Function, db

from werkzeug.routing import PathConverter

from birdseye.utils import path_leaf, all_file_paths, short_path
from littleutils import strip_required_prefix


class FileConverter(PathConverter):
    regex = '.*?'


app.url_map.converters['file'] = FileConverter


@app.route('/')
def index():
    files = sorted(all_file_paths())
    prefix = os.path.commonprefix(files)
    files = zip(files, [strip_required_prefix(f, prefix) or path_leaf(f)
                        for f in files])
    return render_template('index.html',
                           files=files)


@app.route('/file/<file:path>')
def file_view(path):
    return render_template('file.html',
                           funcs=sorted(db.session.query(Function.name).filter_by(file=path).distinct()),
                           full_path=path,
                           short_path=short_path(path))


@app.route('/file/<file:path>/function/<func_name>')
def func_view(path, func_name):
    query = (db.session.query(Call, Function)
             .join(Function)
             .filter_by(file=path, name=func_name)
             .order_by(Call.start_time.desc())
             [:200])

    func = query[0][1]
    return render_template('function.html',
                           func=func,
                           query=query)


@app.route('/call/<int:call_id>')
def call_view(call_id):
    call = Call.query.filter_by(id=call_id).one()
    func = call.function
    return render_template('call.html',
                           call=call,
                           func=func)


def main():
    app.run(debug=True, port=7777)


if __name__ == '__main__':
    main()
