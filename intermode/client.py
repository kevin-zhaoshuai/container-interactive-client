from __future__ import absolute_import

import logging
import os
import select
import socket
import sys
import time
import tty

import termios
from intermode.exc import *

try:
    import websocket
except ImportError:
    logging.fatal('This package requires the "websocket" module.')
    logging.fatal('See http://pypi.python.org/pypi/websocket-client for '
                  'more information.')
    sys.exit()


class Client (object):
    def __init__(self, url,
                 escape='~',
                 close_wait=0.5):
        self.url = url
        self.escape = escape
        self.close_wait = close_wait

        #self.setup_logging()
        self.connect()

    #def setup_logging(self):
   #     logging.getLogger().setLevel(logging.DEBUG)
    #    self.log = logging.getLogger('novaconsole.client')

    def connect(self):
        logging.debug('connecting to: %s', self.url)
        try:
            self.ws = websocket.create_connection(
                self.url)
            logging.warn('connected to: %s', self.url)
            logging.warn('type "%s." to disconnect',
                          self.escape)
        except socket.error as e:
            raise ConnectionFailed(e)
        except websocket.WebSocketConnectionClosedException as e:
            raise ConnectionFailed(e)

    def start_loop(self):
        self.poll = select.poll()
        self.poll.register(sys.stdin,
                           select.POLLIN|select.POLLHUP|select.POLLPRI)
        self.poll.register(self.ws,
                           select.POLLIN|select.POLLHUP|select.POLLPRI)

        self.start_of_line = False
        self.read_escape = False

        try:
            self.setup_tty()
            self.run_forever()

        # here we attempt to translate the exceptions generated
        # by various modules into novaconsole exceptions, so that
        # client code does not need to import modules from all
        # over the place.
        except socket.error as e:
            raise ConnectionFailed(e)
        except websocket.WebSocketConnectionClosedException as e:
            raise Disconnected(e)
        finally:
            self.restore_tty()

    def run_forever(self):
        logging.debug('starting main client loop')
        self.quit = False
        quitting = False
        when = None

        while True:
            for fd, event in self.poll.poll(500):
                if fd == self.ws.fileno():
                    self.handle_websocket(event)
                elif fd == sys.stdin.fileno():
                    self.handle_stdin(event)

            if self.quit and not quitting:
                self.log.debug('entering close_wait')
                quitting = True
                when = time.time() + self.close_wait

            if quitting and time.time() > when:
                self.log.debug('quitting')
                break

    def setup_tty(self):
        if os.isatty(sys.stdin.fileno()):
            logging.debug('putting tty into raw mode')
            self.old_settings = termios.tcgetattr(sys.stdin)
            tty.setraw(sys.stdin)
#        fd = sys.stdin.fileno()
#        old_settings = termios.tcgetattr(fd)
 ##       logging.debug('-----1-----')
 #       try:
#            tty.setraw(sys.stdin.fileno())
 #           logging.debug('---2---')
 #           ch = sys.stdin.read(1)
 #       finally:
 #           termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
 #       return ch

    def restore_tty(self):
        if os.isatty(sys.stdin.fileno()):
            logging.debug('restoring tty configuration')
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN,
                              self.old_settings)

    def handle_stdin(self, event):
        if event in (select.POLLHUP, select.POLLNVAL):
            logging.debug('event %d on stdin', event)

            logging.debug('eof on stdin')
            self.poll.unregister(sys.stdin)
            self.quit = True

        data = os.read(sys.stdin.fileno(), 1024)
        logging.debug('read %s (%d bytes) from stdin',
                       repr(data),
                       len(data))

        if not data:
            return

        if self.start_of_line and data == self.escape:
            self.read_escape = True
            return

        if self.read_escape and data == '.':
            self.log.debug('exit on escape code')
            raise UserExit()
        elif self.read_escape:
            self.read_escape = False
            self.ws.send(self.escape)

        self.ws.send(data)

        if data == '\r':
            self.start_of_line = True
        else:
            self.start_of_line = False

    def handle_websocket(self, event):
        if event in (select.POLLHUP, select.POLLNVAL):
            logging.debug('event %d on websocket', event)

            logging.debug('eof on websocket')
            self.poll.unregister(self.ws)
            self.quit = True

        data = self.ws.recv()
        logging.debug('read %s (%d bytes) from websocket',
                       repr(data),
                       len(data))
        if not data:
            return

        sys.stdout.write(data)
        sys.stdout.flush()
