#!/usr/local/bin/python3
"""
    Copyright (c) 2026 Abdelmonem Awad <eg2@live.com>
    All rights reserved.

    Redistribution and use in source and binary forms, with or without
    modification, are permitted provided that the following conditions are met:

    1. Redistributions of source code must retain the above copyright notice,
       this list of conditions and the following disclaimer.

    2. Redistributions in binary form must reproduce the above copyright
       notice, this list of conditions and the following disclaimer in the
       documentation and/or other materials provided with the distribution.

    THIS SOFTWARE IS PROVIDED ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES,
    INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
    AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
    AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
    OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
    SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
    INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
    CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
    ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
    POSSIBILITY OF SUCH DAMAGE.

    --------------------------------------------------------------------------

    The panel's serial line, for a panel whose bridge LCDd cannot drive.

    The XGS 3300's panel is behind a GIFAR GMRU20X4 bridge, and what it does
    with bytes was measured on 2026-10-17 by writing test patterns and having
    the owner photograph the glass:

      * Every printable character is written at a cursor that then moves on,
        through a ring of forty cells - the twenty of the first row, then the
        twenty of the second, then round to the first again.
      * No command moves that cursor. 0xFE followed by 01, 02, 06, 0C, 28, 80,
        85 or C0 - clear, home, entry mode, display on, function set and the
        line addresses, everything LCDd's hd44780 driver and the vendor's EZIO
        drivers send - is swallowed and does nothing, back to back or with a
        pause. Some other letters after 0xFE (X, G, H) swallow the bytes after
        them too. Nothing tried put the cursor back where it started.
      * Its keys send one letter the moment one goes down - Enter A, Escape B,
        up C, down D - and it answers no request for them.

    That is the whole story of the text that crept around the panel under
    LCDd: it repositions to the first column that changed and writes from
    there, the bridge ignores the reposition, and every update that is not a
    whole screen moves the picture by however many characters it wrote.

    So the plugin draws such a panel itself, and only ever writes whole
    screens: exactly forty characters, never a command. The cursor then comes
    back to the same cell after every screen and the picture cannot move. The
    one thing left to know is which cell that is - wherever earlier writers
    left it, kept across reboots because the bridge keeps it until it loses
    power - and that is the offset in STATE, set once by the owner: the panel
    shows a ruler and the owner says which of its characters is in the top
    left corner, or moves it with the arrow keys from the panel's own menu.
"""

import json
import os
import select
import shlex
import termios
import time

import config

# The instruction escape for each hd44780 serial connection type, from
# LCDproc's hd44780-serial.h, for the panels that do take commands: the
# learning prompts on those are written with a clear and two line starts.
ESCAPES = {
    'ezio': 0xFE,
    'lcdserializer': 0xFE,
    'los-panel': 0xFE,
    'vdr-lcd': 0xFE,
    'pertelian': 0xFE,
}

CLEAR = 0x01
HOME = 0x02
LINE_ONE = 0x80
LINE_TWO = 0xC0

# What an instruction is given before the next byte, as LCDd gives it on this
# connection type (instruction_pause, 40 ms).
INSTRUCTION_PAUSE = 0.04

SPEEDS = {
    1200: termios.B1200,
    2400: termios.B2400,
    4800: termios.B4800,
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
}

# Where the cursor of a ring panel is, as the owner set it.
STATE = '/var/db/frontpanel/glass.json'

# Where `frontpanel.py test` and `frontpanel.py align` leave a request for the
# screen client of a panel drawn here: there is no LCDd to hand it to.
TEST_FILE = '/var/run/frontpanel/test.json'
ALIGN_FILE = '/var/run/frontpanel/align.json'

# The ruler shown while the text is aligned: forty different characters, so
# the one in the top left corner says exactly where the cursor is.
RULER = '0123456789ABCDEFGHIJabcdefghijklmnopqrst'

# How often a whole screen is written again although nothing on it changed:
# insurance against a byte lost on the way, never a reason for the picture to
# move, because a whole screen brings the cursor back to where it was.
REDRAW_SECONDS = 30

# LCDd's screen priorities, highest wins; screens of the same class rotate.
# 'ruler' is the plugin's own, above everything LCDd knows: while the text is
# being aligned, nothing - not even the menu - takes its turn on the glass.
PRIORITY = {'ruler': 5, 'input': 4, 'alert': 3, 'foreground': 2, 'info': 2, 'background': 1}


def printable(text):
    """Only what the bridge writes as one cell: plain ASCII from space to tilde."""
    return ''.join(char if 0x20 <= ord(char) < 0x7f else '?' for char in text)


def load_offset():
    try:
        with open(STATE, 'r') as handle:
            return int(json.load(handle).get('offset', 0)) % len(RULER)
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def save_offset(offset):
    config.write_atomic(STATE, json.dumps({'offset': int(offset) % len(RULER),
                                           'set': int(time.time())}))


class Port(object):
    """The panel's port, opened for reading the keys alongside LCDd, or alone for drawing."""

    def __init__(self, device, speed=None, connection=''):
        """Open the port. With `speed`, take it over and set it up raw; without, leave it as found."""
        flags = os.O_NOCTTY | os.O_NONBLOCK | (os.O_RDWR if speed else os.O_RDONLY)
        self.fd = os.open(device, flags)
        self.escape = ESCAPES.get((connection or '').strip())
        if speed:
            rate = SPEEDS.get(int(speed), termios.B9600)
            attrs = termios.tcgetattr(self.fd)
            attrs[0] = 0
            attrs[1] = 0
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attrs[3] = 0
            attrs[4] = rate
            attrs[5] = rate
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
            termios.tcflush(self.fd, termios.TCIFLUSH)

    def fileno(self):
        return self.fd

    def read(self):
        """Every byte waiting right now, as a list of integers."""
        got = b''
        while True:
            try:
                chunk = os.read(self.fd, 64)
            except (BlockingIOError, InterruptedError):
                break
            if not chunk:
                break
            got += chunk
        return list(got)

    def wait(self, seconds):
        """The first byte to arrive within `seconds`, or None."""
        deadline = time.monotonic() + seconds
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            ready, _, _ = select.select([self.fd], [], [], left)
            if ready:
                found = self.read()
                if found:
                    return found[0]

    def write(self, data):
        os.write(self.fd, data)
        termios.tcdrain(self.fd)

    def ring(self, lines, width, height, offset):
        """A whole screen on a ring panel: every cell written once, starting at the cursor.

        `offset` is the cell the cursor is on. Writing from that cell round to
        the one before it puts each character where it belongs and leaves the
        cursor where it was found.
        """
        cells = ''.join(printable(text or '').ljust(width)[:width]
                        for text in (list(lines) + [''] * height)[:height])
        offset %= len(cells)
        self.write((cells[offset:] + cells[:offset]).encode('ascii'))

    def _instruction(self, byte):
        for value in (self.escape, byte):
            self.write(bytes([value]))
            time.sleep(INSTRUCTION_PAUSE)

    def show(self, lines, width):
        """Two lines on a panel that takes commands: a clear, then each row from its start."""
        if self.escape is None:
            return False
        self._instruction(CLEAR)
        self._instruction(HOME)
        for row, text in enumerate(lines[:2]):
            self._instruction(LINE_TWO if row else LINE_ONE)
            self.write(printable(text).ljust(width)[:width].encode('ascii'))
        return True

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None


class Direct(object):
    """LCDd's part, played by the plugin, for a ring panel LCDd cannot drive.

    It answers the handful of LCDd commands the screen client sends and hands
    back the events LCDd would - `listen` when a screen comes up, `ignore`
    when it goes, `key` for a press - so the client works the same against
    either. What it writes is only ever a whole screen; see the module's
    description for why.
    """

    def __init__(self, options, panel):
        self.device = options['device']
        self.speed = config.serial_speed(options, panel)
        self.width, self.height = config.geometry(options['size']) or (16, 2)
        self.wait = max(1, int(options.get('screen_seconds') or 3))
        self.codes = config.key_codes(options, panel) if options['keypad'] else {}
        self.version = 'direct'
        self.protocol = ''
        self.port = None
        self.sock = None
        self.screens = {}
        self.added = 0
        self.visible = ''
        self.since = 0.0
        self.drawn = None
        self.drawn_at = 0.0
        if (panel or {}).get('offset') and not os.path.exists(STATE):
            # Nobody has lined this panel up yet: start where its entry says the
            # cursor was found on a panel of this model, and keep that, so the
            # page's ruler counts from the same cell this draws from.
            save_offset(panel['offset'])
        self.offset = load_offset()
        self.offset_at = self._stamp()
        self.events = []

    @staticmethod
    def _stamp():
        try:
            return os.path.getmtime(STATE)
        except OSError:
            return 0.0

    def open(self, name='', timeout=0):
        self.close()
        self.port = Port(self.device, self.speed)
        self.sock = self.port
        self.screens = {}
        self.visible = ''
        self.drawn = None
        return 'direct'

    def close(self):
        if self.port is not None:
            # A blank screen is forty spaces: it clears the glass and leaves the
            # cursor where the next start will expect it.
            try:
                self.port.ring([], self.width, self.height, self.offset)
            except OSError:
                pass
            self.port.close()
        self.port = None
        self.sock = None

    # -- alignment ----------------------------------------------------------

    @property
    def ruler_on(self):
        return '_ruler' in self.screens

    def show_ruler(self, seconds=180):
        """The ruler on the glass: forty different characters, '0' meant for the top left."""
        ring = self.width * self.height
        ruler = (RULER * (ring // len(RULER) + 1))[:ring]
        lines = [ruler[row * self.width:(row + 1) * self.width] for row in range(self.height)]
        self._add('_ruler', 'ruler', lines, time.monotonic() + max(10, min(600, int(seconds))))

    def hide_ruler(self):
        self.screens.pop('_ruler', None)

    def shift(self, step):
        """Move the picture one cell, and keep where it now is.

        Kept at once rather than on a confirmation: the page works out where the
        cursor is from the offset kept on disk, so the two must never disagree.
        """
        self.offset = (self.offset + step) % (self.width * self.height)
        save_offset(self.offset)
        self.offset_at = self._stamp()
        self.drawn = None

    # -- the commands the client sends ------------------------------------

    def send(self, line):
        try:
            words = shlex.split(line)
        except ValueError:
            return
        if len(words) < 2:
            return
        command, key = words[0], words[1]
        if command == 'screen_add':
            if key not in self.screens:
                self.added += 1
                self.screens[key] = {'priority': 'foreground', 'lines': ['', ''],
                                     'expires': None, 'order': self.added}
        elif command == 'screen_del':
            self.screens.pop(key, None)
        elif command == 'screen_set' and key in self.screens:
            screen = self.screens[key]
            options = dict(zip(words[2::2], words[3::2]))
            if options.get('-priority') in PRIORITY:
                screen['priority'] = options['-priority']
            if options.get('-timeout', '').isdigit():
                # LCDd counts it in eighths of a second.
                screen['expires'] = time.monotonic() + int(options['-timeout']) / 8.0
        elif command == 'widget_set' and key in self.screens and len(words) >= 6:
            row = {'l1': 0, 'l2': 1}.get(words[2])
            if row is not None:
                self.screens[key]['lines'][row] = words[5]

    # -- what LCDd would say back -----------------------------------------

    def drain(self, timeout=0.0):
        self.schedule()
        if not self.events and self.port is not None:
            ready, _, _ = select.select([self.port], [], [], max(0.0, timeout))
            if ready:
                for byte in self.port.read():
                    name = self.codes.get(byte)
                    if name:
                        self.events.append('key %s' % name)
            self.schedule()
        events, self.events = self.events, []
        return events

    def schedule(self):
        """Choose the screen on the glass as LCDd would, and draw it if it changed."""
        if self.port is None:
            return
        now = time.monotonic()
        self.requests(now)
        for key in [key for key, screen in self.screens.items()
                    if screen['expires'] is not None and now >= screen['expires']]:
            del self.screens[key]

        current = self.visible
        if self.screens:
            top = max(PRIORITY.get(screen['priority'], 0) for screen in self.screens.values())
            group = sorted((key for key, screen in self.screens.items()
                            if PRIORITY.get(screen['priority'], 0) == top),
                           key=lambda key: self.screens[key]['order'])
            if current not in group:
                current = group[0]
                self.since = now
            elif len(group) > 1 and now - self.since >= self.wait:
                current = group[(group.index(current) + 1) % len(group)]
                self.since = now
        else:
            current = ''

        if current != self.visible:
            if self.visible:
                self.events.append('ignore %s' % self.visible)
            if current:
                self.events.append('listen %s' % current)
            self.visible = current

        lines = list(self.screens[self.visible]['lines']) if self.visible else []
        if lines != self.drawn or now - self.drawn_at >= REDRAW_SECONDS:
            self.port.ring(lines, self.width, self.height, self.offset)
            self.drawn = lines
            self.drawn_at = now

    def requests(self, now):
        """What the commands on the page asked for: a new offset, a test line, the ruler."""
        stamp = self._stamp()
        if stamp != self.offset_at:
            self.offset_at = stamp
            self.offset = load_offset()
            self.drawn = None

        wanted = self._take(TEST_FILE)
        if wanted is not None:
            lines = [str(line) for line in (wanted.get('lines') or [])][:2] + ['', '']
            self._add('_test', 'alert', lines[:2], now + max(1, min(30, int(wanted.get('seconds') or 5))))

        wanted = self._take(ALIGN_FILE)
        if wanted is not None:
            if wanted.get('show'):
                self.show_ruler(wanted.get('seconds') or 180)
            else:
                self.hide_ruler()

    def _add(self, key, priority, lines, expires):
        self.added += 1
        self.screens[key] = {'priority': priority, 'lines': lines, 'expires': expires,
                             'order': self.added}

    @staticmethod
    def _take(path):
        try:
            with open(path, 'r') as handle:
                wanted = json.load(handle)
            os.unlink(path)
        except (OSError, ValueError):
            return None
        return wanted if isinstance(wanted, dict) else None
