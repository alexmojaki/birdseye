import inspect
import socket
import sys
from io import BytesIO, StringIO
from threading import currentThread, Thread

from IPython.core.display import HTML, display
from IPython.core.magic import Magics, cell_magic, magics_class
from jinja2 import Environment, PackageLoader, select_autoescape
from traitlets import Unicode, Int
from werkzeug.local import LocalProxy
from werkzeug.serving import ThreadingMixIn

from birdseye import eye, PY2
from birdseye.server import app

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


def run_server(port, bind_host):
    thread_proxies[currentThread().ident] = fake_stream()
    try:
        app.run(
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

    # def __init__(self, **kwargs):
    #     super(BirdsEyeMagics, self).__init__(**kwargs)
    #     self.server_url = self.server_url

    @cell_magic
    def eye(self, _line, cell):
        Thread(target=run_server, args=(self.port, self.bind_host)).start()

        call_id, value = eye.exec_ipython_cell(cell)

        if self.server_url:
            url = self.server_url.rstrip('/')
        else:
            url = 'http://localhost:%s' % self.port

        html = HTML(templates_env.get_template('ipython_iframe.html').render(
            call_id=call_id,
            url=url,
        ))

        # noinspection PyTypeChecker
        display(html)

        # Display the value as would happen if the %eye magic wasn't there
        return value
