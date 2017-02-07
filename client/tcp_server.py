# Simple TCP server with a callback that gets called when
# data arrives over the TCP interface.
#
# This requires Python 3, mostly due to lazyness.

import socket
import threading
import socketserver


class ThreadedTCPRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        while True:
            try:
                stuff = self.request.recv(256)
            except ConnectionResetError:
                stuff = None
            if not stuff:
                print('socket closed')
                break
            self.server.callback(stuff)


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    def __init__(self, callback, *args, **kwargs):
        self.callback = callback
        super().__init__(*args, **kwargs)


class SimpleTcpServer:
    def __init__(self, port, callback):
        self.server = ThreadedTCPServer(callback, ('localhost', port),
                                        ThreadedTCPRequestHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever)

        # Exit the server thread when the main thread terminates.
        self.server_thread.daemon = True
        self.server_thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


if __name__ == "__main__":

    def cb(line):
        print('cb: %s' % line)

    server = SimpleTcpServer(5123, cb)

    import time
    time.sleep(10)

    server.stop()
