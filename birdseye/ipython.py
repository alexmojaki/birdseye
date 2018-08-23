import inspect
import socket
import sys
from io import BytesIO, StringIO
from threading import currentThread, Thread
from uuid import uuid4

from IPython.core.display import HTML, display
from IPython.core.magic import Magics, cell_magic, magics_class
from jinja2 import Environment, PackageLoader, select_autoescape
from traitlets import Unicode, Int, Bool
from werkzeug.local import LocalProxy
from werkzeug.serving import ThreadingMixIn

from birdseye import PY2, Database, eye
from birdseye import server

fake_stream = BytesIO if PY2 else StringIO

thread_proxies = {}


def stream_proxy(original):
    def p():
        frame = inspect.currentframe()
        while frame:
            if frame.f_code == ThreadingMixIn.process_request_thread.__code__:
                return fake_stream()
            frame = frame.f_back
        return thread_proxies.get(currentThread().ident,
                                  original)

    return LocalProxy(p)


sys.stderr = stream_proxy(sys.stderr)
sys.stdout = stream_proxy(sys.stdout)


def run_server(port, bind_host, show_server_output):
    if not show_server_output:
        thread_proxies[currentThread().ident] = fake_stream()
    try:
        server.app.run(
            debug=True,
            port=port,
            host=bind_host,
            use_reloader=False,
        )
    except socket.error:
        pass


templates_env = Environment(
    loader=PackageLoader('birdseye', 'templates'),
    autoescape=select_autoescape(['html', 'xml'])
)


@magics_class
class BirdsEyeMagics(Magics):
    server_url = Unicode(u'', config=True)
    port = Int(7777, config=True)
    bind_host = Unicode('127.0.0.1', config=True)
    show_server_output = Bool(False, config=True)
    db_url = Unicode(u'', config=True)

    @cell_magic
    def eye(self, _line, cell):
        if not self.server_url:
            server.db = Database(self.db_url)
            server.Function = server.db.Function
            server.Call = server.db.Call
            server.Session = server.db.Session
            Thread(
                target=run_server,
                args=(
                    self.port,
                    self.bind_host,
                    self.show_server_output,
                ),
            ).start()

        eye.db = Database(self.db_url)

        def callback(call_id):
            """
            Always executes after the cell, whether or not an exception is raised
            in the user code.
            """
            if call_id is None:  # probably means a bug
                return

            html = HTML(templates_env.get_template('ipython_iframe.html').render(
                call_id=call_id,
                url=self.server_url.rstrip('/'),
                port=self.port,
                container_id=uuid4().hex,
            ))

            # noinspection PyTypeChecker
            display(html)

        value = eye.exec_ipython_cell(cell, callback)
        # Display the value as would happen if the %eye magic wasn't there
        return value
