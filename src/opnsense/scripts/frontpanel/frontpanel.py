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

    Front Panel - the command every other part of the plugin goes through.

        frontpanel.py build-config     write LCDd.conf from the settings
        frontpanel.py start            build it, then start LCDd and the client
        frontpanel.py stop             stop both
        frontpanel.py restart          stop, then start
        frontpanel.py status           what is running, and what the panel says
        frontpanel.py test [line]      write one line to the panel and take it back
        frontpanel.py screens          what each screen would show right now
        frontpanel.py keys             what the driver has reported since it started
        frontpanel.py learn [seconds]  stop the feeder, listen, say which key spoke
        frontpanel.py panels           the appliance table, joined to this machine
        frontpanel.py diagnostics      the keys and the panels report in one answer
        frontpanel.py client           the screen client itself (started by `start`)

    ---------------------------------------------------------------------------

    Why this file speaks LCDd's protocol itself instead of running the client
    that comes in the package.

    LCDproc ships a client, /usr/local/bin/lcdproc, and it is a good one - the
    owner's first working panel was drawn by it. But its screens are the ones
    it was compiled with: clock, CPU, memory, uptime, load. There is no way to
    add "the WAN address and whether the gateway answers", or "the worst port
    os-linkhealth can see", because a screen in that client is C code, not
    configuration. Everything this plugin exists to show would have to be left
    out, and what it would show instead is the part a firewall's own dashboard
    already shows better.

    The alternative is not expensive. LCDd's protocol is one line of text per
    command over a TCP socket on the loopback address:

        hello                                 -> connect LCDproc 0.5.9 ... wid 16 hgt 2 ...
        client_set -name frontpanel           -> success
        screen_add wan                        -> success
        screen_set wan -priority foreground   -> success
        widget_add wan l1 string              -> success
        widget_set wan l1 1 1 "WAN ok 14ms"   -> success

    and the server pushes three things back without being asked: `listen <id>`
    when a screen becomes the visible one, `ignore <id>` when it stops being,
    and `key <name>` when a key the client reserved is pressed. That is the
    whole of what is needed here, it is a documented, stable protocol, and it
    keeps every decision about what the panel says inside this plugin where the
    settings page can reach it.

    Two consequences worth stating plainly:

      * between one minute and the next, only the screen on the glass is
        recomputed. `listen` is the signal to refresh it, and it is refreshed
        again every couple of seconds after that. Once a minute every screen is
        generated, because asking a screen whether it still has anything to say
        means generating it - that is how the ports screen appears by itself
        when somebody installs os-linkhealth, and how it leaves again if they
        remove it.

      * the rotation speed is not ours. screen_seconds is written into LCDd's
        own WaitTime and LCDd does the rotating, so the number on the settings
        page is the number the server is using, not an approximation of it kept
        in a loop here.
"""

import json
import os
import re
import select
import signal
import socket
import subprocess
import sys
import syslog
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config    # noqa: E402
import keys as keypad  # noqa: E402
import screens   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = '/usr/local/bin/python3'
DAEMON = '/usr/sbin/daemon'
LCDD = '/usr/local/sbin/LCDd'

RUN_DIR = '/var/run/frontpanel'
LOG_DIR = '/var/log/frontpanel'
STATE_DIR = '/var/db/frontpanel'

LCDD_PID = os.path.join(RUN_DIR, 'LCDd.pid')
LCDD_SUPERVISOR = os.path.join(RUN_DIR, 'LCDd.supervisor.pid')
CLIENT_PID = os.path.join(RUN_DIR, 'client.pid')
CLIENT_SUPERVISOR = os.path.join(RUN_DIR, 'client.supervisor.pid')

LCDD_LOG = keypad.LOG
CLIENT_LOG = os.path.join(LOG_DIR, 'client.log')

CLIENT_NAME = 'frontpanel'
TEST_SCREEN = '_test'
EMPTY_SCREEN = '_empty'
MENU_SCREEN = '_menu'
LEARN_SCREEN = '_learn'

# Screens the plugin puts up for its own reasons. None of them is part of the
# rotation the keys step through.
INTERNAL_SCREENS = (TEST_SCREEN, EMPTY_SCREEN, MENU_SCREEN, LEARN_SCREEN)

# Of those, the ones somebody else is holding open. The availability sweep must
# not take a menu off the glass from under a finger; the "nothing to show"
# screen is the sweep's own and does come and go with it.
HELD_SCREENS = (TEST_SCREEN, MENU_SCREEN, LEARN_SCREEN)

# How long a menu stays open with nobody pressing anything. Same reasoning as
# the pin watchdog: a panel in a rack must always find its own way back.
MENU_SECONDS = 30

# How long to wait for LCDd to open its socket after being started. The serial
# driver initialises the panel first, and on a 2400 baud line that is not
# instant.
STARTUP_SECONDS = 12

# How often the visible screen is recomputed. Fast enough that a throughput
# figure feels live, slow enough that seven sysctl calls a second never happen.
# Recomputing is not the same as writing: a value that has not changed is not
# sent to the panel at all.
CONTENT_SECONDS = 2

# How long the loop waits for the server to say something. Short inside a menu,
# where a person is standing there pressing buttons; longer while idle, where
# nothing is expected and a wakeup every half second is already generous.
MENU_POLL = 0.1
IDLE_POLL = 0.5

# How often the client asks again which screens have something to say, so that
# installing os-linkhealth makes the ports screen appear without a restart.
AVAILABILITY_SECONDS = 60

# A key press pins the panel to one screen. This is how long that lasts if
# nobody presses anything else: a rack panel that somebody brushed past must
# not still be frozen on one screen an hour later.
PINNED_SECONDS = 120

# The four names this plugin was written against, behind everything else. They
# are the ones panels.json ships for the appliance whose keypad was measured,
# and the ones keys.py gives an action to when nobody has said otherwise.
DEFAULT_KEYS = ['Enter', 'Up', 'Down', 'Escape']

# A key name as LCDd.conf may spell one. Narrow on purpose: these go into a
# command line sent to the server, where a space would start another argument.
_KEY_NAME = re.compile(r'^[A-Za-z0-9_]{1,32}$')

_GREETING = re.compile(r'\bwid\s+(\d+)\s+hgt\s+(\d+)')
_VERSION = re.compile(r'^connect\s+LCDproc\s+(\S+)\s+protocol\s+(\S+)')

_stopping = False


def log(message, level=syslog.LOG_NOTICE):
    syslog.openlog('frontpanel', syslog.LOG_PID, syslog.LOG_DAEMON)
    syslog.syslog(level, message)
    syslog.closelog()


# ---------------------------------------------------------------------------
# The socket
# ---------------------------------------------------------------------------

class Panel(object):
    """A client connection to LCDd, as a handful of lines of text."""

    def __init__(self, host=config.BIND, port=config.PORT):
        self.host = host
        self.port = port
        self.sock = None
        self.buffer = b''
        self.width = 0
        self.height = 0
        self.version = ''
        self.protocol = ''

    def open(self, name=CLIENT_NAME, timeout=5.0):
        """Connect and complete the handshake, or raise.

        The greeting carries the size the driver reported, which is the only
        authority on how wide the display really is. The settings page's `size`
        is what LCDd was asked for; this is what it got.
        """
        self.sock = socket.create_connection((self.host, self.port), timeout)
        self.sock.settimeout(None)
        self.send('hello')

        greeting = self.readline(timeout)
        if not greeting or not greeting.startswith('connect'):
            raise IOError('LCDd did not answer hello: %s' % (greeting or 'nothing at all'))

        found = _GREETING.search(greeting)
        if found:
            self.width, self.height = int(found.group(1)), int(found.group(2))
        found = _VERSION.match(greeting)
        if found:
            self.version, self.protocol = found.group(1), found.group(2)

        self.send('client_set -name %s' % name)
        return greeting

    def send(self, line):
        if self.sock is None:
            raise IOError('not connected')
        self.sock.sendall((line + '\n').encode('ascii', 'replace'))

    def _fill(self, timeout):
        ready, _, _ = select.select([self.sock], [], [], max(0.0, timeout))
        if not ready:
            return False
        chunk = self.sock.recv(4096)
        if not chunk:
            raise IOError('LCDd closed the connection')
        self.buffer += chunk
        return True

    def readline(self, timeout=5.0):
        """One line from the server, or None when the wait ran out."""
        deadline = time.monotonic() + timeout
        while True:
            if b'\n' in self.buffer:
                line, _, self.buffer = self.buffer.partition(b'\n')
                return line.decode('ascii', 'replace').strip()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._fill(remaining)

    def drain(self, timeout=0.0):
        """Every line waiting right now, without blocking for more."""
        lines = []
        while True:
            if b'\n' in self.buffer:
                line, _, self.buffer = self.buffer.partition(b'\n')
                lines.append(line.decode('ascii', 'replace').strip())
                continue
            if not self._fill(timeout):
                return lines
            timeout = 0.0

    def close(self):
        """Leave. Closing the socket is how a client says goodbye to LCDd -
        the server drops the client and every screen it owned."""
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


def quoted(text):
    """A string LCDd's line parser will read back as one argument.

    The parser takes double quotes around an argument containing spaces. Rather
    than depend on how it treats an escaped quote inside one, the two
    characters that could end the argument early are swapped for ones that
    cannot: a straight quote becomes an apostrophe and a backslash a stroke.
    On a sixteen-column panel neither substitution loses anything a reader
    would miss.
    """
    safe = screens.fold(text).replace('\\', '/').replace('"', "'")
    return '"%s"' % safe


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------

def ensure_dirs():
    for path, mode in ((RUN_DIR, 0o755), (LOG_DIR, 0o750), (STATE_DIR, 0o750)):
        os.makedirs(path, mode=mode, exist_ok=True)
        try:
            os.chmod(path, mode)
        except OSError:
            pass


def read_pid(path):
    try:
        with open(path, 'r') as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def alive(pid):
    if not pid or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # somebody else's, but it exists


def running(path):
    pid = read_pid(path)
    return (pid if alive(pid) else None)


def spawn(args, name):
    """Start something under daemon(8) and let it detach.

    daemon(8) rather than a bare fork: it writes the pid files this module
    reads back, and it owns the redirection of the child's output into a log
    file - which for LCDd is not a nicety, because everything LCDd reports,
    including every key the driver sees, comes out on its standard error.

    Every caller passes -f, and it is not optional. Without it daemon(8) leaves
    its own standard output and error as it found them, which here are the
    pipes this function is reading: the read then does not finish until the
    process being supervised does, so starting something that is meant to run
    for weeks would sit here until the timeout and then be reported as a
    failure that had in fact succeeded. Measured on this machine, 2026-09-21:
    daemon -f returned immediately, the same command without it took exactly as
    long as the child it was supervising. -o still writes the child's output to
    the log either way, which was measured at the same time.
    """
    try:
        done = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as failure:
        return 'could not start %s: %s' % (name, failure)

    if done.returncode != 0:
        detail = (done.stderr or done.stdout or '').strip()
        return 'could not start %s: %s' % (name, detail or 'exit %d' % done.returncode)
    return ''


def terminate(supervisor_path, child_path, name, grace=6.0):
    """Ask a supervised process to stop, and make sure it did.

    The supervisor is asked first because it forwards the signal and then stops
    restarting anything; the child is only signalled directly if it outlives
    it. SIGKILL is a last resort and is reported, because a panel driver that
    will not answer SIGTERM is worth knowing about.
    """
    stopped = []
    for path in (supervisor_path, child_path):
        pid = running(path)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                stopped.append(pid)
            except OSError:
                pass

    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not running(supervisor_path) and not running(child_path):
            return ''
        time.sleep(0.2)

    killed = []
    for path in (supervisor_path, child_path):
        pid = running(path)
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
                killed.append(pid)
            except OSError:
                pass

    if killed:
        message = '%s did not answer SIGTERM and was killed (%s)' % (
            name, ', '.join(str(pid) for pid in killed))
        log(message, syslog.LOG_WARNING)
        return message
    return ''


def rotate(path):
    """Keep one previous log and start the current one empty.

    Two reasons. The key test reports what has arrived "since it started", and
    that is only true if the log it reads starts when the service does. And
    with the keypad switched on LCDd is asked for a level at which it writes a
    line per keystroke - quiet on a rack appliance, but a file nobody ever
    truncated would still grow for as long as the panel runs.
    """
    try:
        if os.path.exists(path):
            os.replace(path, path + '.1')
    except OSError:
        pass


def log_tail(path, lines=12, only_errors=False):
    """The last few lines of a log, for a status answer that explains itself."""
    text = keypad.tail(path, 64 * 1024)
    found = [line.rstrip() for line in text.splitlines() if line.strip()]
    if only_errors:
        found = [line for line in found
                 if re.search(r'error|cannot|could not|fail|unable|invalid', line, re.I)]
    return found[-lines:]


# ---------------------------------------------------------------------------
# The screen client
# ---------------------------------------------------------------------------

def wanted_keys(options):
    """The key names to ask LCDd for, for this installation's own keypad.

    Not a fixed four. The name written beside each matrix position is the
    owner's - that column exists because a map measured on a Sophos XG 330 is
    not a fact about anybody else's metal - and a position LCDd.conf calls
    `Left` arrives from the server as `Left`. A client that reserved only the
    four names this plugin was written against would leave that press to the
    server, where nothing of ours can see it, and the button would be dead with
    nothing on the settings page able to explain why.

    So: the names the key grid uses, then the ones panels.json ships for this
    appliance - which is what the generated configuration writes when the grid
    is empty - then the four defaults behind both. Reserving a name that never
    arrives costs nothing, and a shared reservation takes nothing away from
    anybody else even then.
    """
    names = []

    def keep(name):
        name = (name or '').strip()
        if name and name not in names and _KEY_NAME.match(name):
            names.append(name)

    for row in options.get('keys') or []:
        keep(row.get('key'))

    try:
        _, panel = config.match_panel()
        for name in (panel.get('keymap') or {}).values():
            keep(name)
    except Exception:
        # A table that cannot be read is not a reason to go without keys; the
        # four below are what this appliance reports anyway.
        pass

    for name in DEFAULT_KEYS:
        keep(name)
    return names


class Client(object):
    """Keeps LCDd supplied with screens for as long as it is asked to."""

    def __init__(self, options):
        self.options = options
        self.panel = Panel()
        self.width, self.height = config.geometry(options['size']) or (16, 2)
        self.actions = keypad.actions_for(options)
        self.added = []        # screen keys currently known to LCDd
        self.shown = {}        # what is on each screen, so we can not rewrite it
        self.visible = ''      # what LCDd last said it was showing
        self.pinned = ''       # a screen a key press stuck us on, or ''
        self.pinned_at = 0.0
        self.menu = None       # index into menu_order(), or None when closed
        self.menu_at = 0.0
        self.content_at = 0.0
        self.availability_at = 0.0
        try:
            self.config_at = os.path.getmtime(config.CONFIG_XML)
        except OSError:
            self.config_at = 0.0

    # -- setup ------------------------------------------------------------

    def connect(self):
        self.panel.open(CLIENT_NAME)
        if self.panel.width and self.panel.height:
            # What the driver reports beats what the settings asked for.
            self.width, self.height = self.panel.width, self.panel.height

        if self.options['keypad']:
            # -shared, not -exclusively: we want the keys while our screens are
            # up, not to take them away from anything else that might be here.
            names = wanted_keys(self.options)
            if names:
                self.panel.send('client_add_key -shared %s' % ' '.join(names))

        self.added = []
        self.shown = {}
        self.visible = ''
        self.pinned = ''
        self.menu = None
        self.refresh_screens()

    def add_screen(self, key, lines):
        self.panel.send('screen_add %s' % key)
        self.panel.send('screen_set %s -name %s -priority foreground'
                        % (key, quoted(key)))
        self.panel.send('widget_add %s l1 string' % key)
        self.panel.send('widget_add %s l2 string' % key)
        self.added.append(key)
        self.write(key, lines)

    def remove_screen(self, key):
        self.panel.send('screen_del %s' % key)
        if key in self.added:
            self.added.remove(key)
        self.shown.pop(key, None)
        if self.pinned == key:
            self.pinned = ''

    def write(self, key, lines):
        """Put two finished lines on a screen, if they are not there already.

        The "if" is the important half. On this appliance the display and the
        keypad share one 2400 baud line, and every byte written to the panel is
        a byte the driver is not spending polling the keys: with the screen
        being redrawn on a timer, two thirds of key presses were lost, and with
        it quiet every one arrived. So a line whose text has not changed is not
        sent, and a screen showing a steady value costs nothing at all.

        Rows beyond the second are left alone. A screen generator returns two
        lines by contract, and on a four-row panel writing blanks into rows
        three and four would be a guess about what belongs there.
        """
        first = lines[0] if lines else ''
        second = lines[1] if len(lines) > 1 else ''
        before = self.shown.get(key, (None, None))

        if first != before[0]:
            self.panel.send('widget_set %s l1 1 1 %s' % (key, quoted(first)))
        if self.height >= 2 and second != before[1]:
            self.panel.send('widget_set %s l2 1 2 %s' % (key, quoted(second)))

        self.shown[key] = (first, second)

    # -- content ----------------------------------------------------------

    def refresh_screens(self):
        """Add the screens that have something to say, drop the ones that do not.

        Finding out whether a screen still has anything to say means asking it,
        so every screen is generated here - which is why this runs once a
        minute rather than in the refresh loop. Between two of these, only the
        screen on the glass is recomputed.
        """
        self.availability_at = time.monotonic()
        wanted = []
        for key in screens.chosen(self.options):
            lines = screens.render(key, self.width, self.height, self.options)
            if lines is not None:
                wanted.append((key, lines))

        if not wanted:
            # Everything the owner asked for is silent - only the ports screen
            # enabled on a machine without os-linkhealth, say. Say so on the
            # glass rather than leaving a dark panel that looks broken.
            wanted = [(EMPTY_SCREEN, [screens.cut('Front Panel', self.width),
                                      screens.cut('no screens', self.width)])]

        present = set(self.added)
        names = [key for key, _ in wanted]

        for key, lines in wanted:
            if key not in present:
                self.add_screen(key, lines)
            else:
                # The lines had to be generated to answer the question above,
                # so writing them costs nothing more and leaves every screen
                # current rather than only the visible one.
                self.write(key, lines)

        for key in list(self.added):
            if key not in names and key not in HELD_SCREENS:
                self.remove_screen(key)

    def refresh_visible(self):
        """Recompute whatever is on the glass right now, and nothing else."""
        self.content_at = time.monotonic()
        if self.menu is not None:
            # The menu is what is on the glass, and a key is expected. Writing
            # anything now is writing over it and starving the poll that is
            # waiting for the next press.
            return
        key = self.visible or (self.added[0] if self.added else '')
        if not key or key in INTERNAL_SCREENS:
            return
        lines = screens.render(key, self.width, self.height, self.options)
        if lines is None:
            # It had something to say when it was added and has nothing now.
            self.refresh_screens()
            return
        self.write(key, lines)

    # -- keys -------------------------------------------------------------

    def pin(self, key):
        """Hold one screen on the glass, by outranking the rotation.

        LCDd shows the highest priority screen and rotates only among equals,
        so raising one screen to `alert` is all "stop here" means.
        """
        if not key or key not in self.added:
            return
        self.pinned = key
        self.pinned_at = time.monotonic()
        for name in self.added:
            self.panel.send('screen_set %s -priority %s'
                            % (name, 'alert' if name == key else 'foreground'))
        lines = screens.render(key, self.width, self.height, self.options)
        if lines is not None:
            self.write(key, lines)

    def unpin(self):
        self.pinned = ''
        for name in self.added:
            self.panel.send('screen_set %s -priority foreground' % name)

    def reload(self):
        """Pick up a settings change that did not need LCDd restarted.

        Which button does what, which screens are shown and in what order, and
        the owner's message all live in this process rather than in LCDd.conf,
        so changing one of them should not cost the panel a restart - and does
        not. The configuration is only re-read when it has actually been
        written, which on an idle firewall is never.
        """
        try:
            stamp = os.path.getmtime(config.CONFIG_XML)
        except OSError:
            return
        if stamp == self.config_at:
            return

        self.config_at = stamp
        fresh = config.settings()

        # Anything LCDd itself had to be told - the driver, the port, the
        # speeds - is not adopted here: that is a new LCDd.conf and a restart,
        # and `start` does it by comparing the file it wrote.
        for name in ('screens', 'message', 'throughput_if', 'keys', 'keypad'):
            self.options[name] = fresh[name]
        self.actions = keypad.actions_for(self.options)

    def order(self):
        """The screens in the order the settings asked for them.

        Not the order they happened to be added in: a screen that appeared
        later - the ports screen, after somebody installed os-linkhealth -
        belongs in its place rather than at the end.
        """
        wanted = [key for key in screens.chosen(self.options) if key in self.added]
        wanted += [key for key in self.added
                   if key not in wanted and key not in INTERNAL_SCREENS]
        return wanted

    def step(self, direction):
        order = self.order()
        if not order:
            return
        current = self.pinned or self.visible
        try:
            index = order.index(current)
        except ValueError:
            index = 0
        self.pin(order[(index + direction) % len(order)])

    # -- the menu ---------------------------------------------------------

    def open_menu(self):
        """A list of the screens, on the glass, with the feeder silent.

        `input` is the priority above everything else LCDd knows about, so the
        menu cannot be rotated out from under a finger. Nothing else is written
        while it is open: the whole reason the menu is usable on this appliance
        is that a quiet bus is a bus that does not swallow key presses.
        """
        order = self.order()
        if not order:
            return

        current = self.pinned or self.visible
        self.menu = order.index(current) if current in order else 0
        self.menu_at = time.monotonic()

        if MENU_SCREEN not in self.added:
            self.panel.send('screen_add %s' % MENU_SCREEN)
            self.panel.send('widget_add %s l1 string' % MENU_SCREEN)
            self.panel.send('widget_add %s l2 string' % MENU_SCREEN)
            self.added.append(MENU_SCREEN)
        self.panel.send('screen_set %s -name %s -priority input -timeout %d'
                        % (MENU_SCREEN, quoted('menu'), (MENU_SECONDS + 5) * 8))
        self.draw_menu()

    def draw_menu(self):
        order = self.order()
        if self.menu is None or not order:
            return
        self.menu = self.menu % len(order)
        key = order[self.menu]
        title = screens.BY_KEY.get(key, (key,))[0]
        self.write(MENU_SCREEN, [
            screens.cut('Screens %d/%d' % (self.menu + 1, len(order)), self.width),
            screens.cut('> ' + title, self.width),
        ])

    def move_menu(self, direction):
        if self.menu is None:
            return
        self.menu += direction
        self.menu_at = time.monotonic()
        self.draw_menu()

    def close_menu(self):
        if self.menu is None:
            return
        self.menu = None
        if MENU_SCREEN in self.added:
            self.remove_screen(MENU_SCREEN)

    def confirm_menu(self):
        order = self.order()
        if self.menu is None or not order:
            return
        key = order[self.menu % len(order)]
        self.close_menu()
        self.pin(key)

    # -- what a button does -----------------------------------------------

    def act(self, action, target):
        if action == 'next':
            self.step(1)
        elif action == 'previous':
            self.step(-1)
        elif action == 'menu':
            self.open_menu()
        elif action == 'back':
            self.unpin()
        elif action == 'screen':
            self.pin(target)
        elif action == 'backlight':
            # Whether anything happens is the driver's business; LCDd takes the
            # command from any client and the ones that cannot do it ignore it.
            self.panel.send('backlight toggle')

    def key(self, name):
        """What a press does.

        None of it is required for the plugin to work: the screens rotate on a
        timer and a panel whose keys never report is still a useful panel. The
        actions themselves come from the settings, because the map measured on
        one appliance is not a fact about anybody else's.
        """
        try:
            keypad.record_press(name)
        except Exception as failure:
            print('could not record key %s: %s' % (name, failure), file=sys.stderr)

        action, target = self.actions.get(name, ('none', ''))

        if self.menu is not None:
            if action == 'next':
                self.move_menu(1)
            elif action == 'previous':
                self.move_menu(-1)
            elif action == 'menu':
                self.confirm_menu()
            else:
                # Anything else leaves the menu first, so a key with an unusual
                # action cannot act from underneath it.
                self.close_menu()
                if action != 'back':
                    self.act(action, target)
            return

        self.act(action, target)

    # -- the loop ---------------------------------------------------------

    def handle(self, line):
        if line.startswith('listen '):
            self.visible = line.split(None, 1)[1].strip()
            if self.menu is None and self.visible not in INTERNAL_SCREENS:
                self.refresh_visible()
        elif line.startswith('key '):
            self.key(line.split(None, 1)[1].strip())
        elif line.startswith('huh?'):
            # LCDd refused something. Worth a line in the log and nothing more:
            # one rejected screen must not stop the other six.
            print('LCDd: %s' % line, file=sys.stderr)

    def serve(self):
        """One connection, for as long as it lasts."""
        self.connect()
        print('connected to LCDd %s, protocol %s, %dx%d'
              % (self.panel.version or '?', self.panel.protocol or '?',
                 self.width, self.height), file=sys.stderr)

        while not _stopping:
            # Faster while a key is expected, slower while idle. This is the
            # client's own reaction time rather than the driver's polling of
            # the wire, but it is the half we own, and answering a press in a
            # tenth of a second instead of half of one is what makes stepping
            # through a menu feel like a menu.
            for line in self.panel.drain(MENU_POLL if self.menu is not None else IDLE_POLL):
                self.handle(line)

            now = time.monotonic()

            if self.menu is not None:
                # Nothing is written while the menu is up. A quiet bus is the
                # whole reason the keys are reliable on this appliance.
                if now - self.menu_at >= MENU_SECONDS:
                    self.close_menu()
                continue

            if now - self.content_at >= CONTENT_SECONDS:
                self.refresh_visible()
            if now - self.availability_at >= AVAILABILITY_SECONDS:
                self.reload()
                self.refresh_screens()
            if self.pinned and now - self.pinned_at >= PINNED_SECONDS:
                self.unpin()

    def run(self):
        """Keep serving, and keep coming back when LCDd goes away.

        LCDd is restarted whenever a setting changes, and the client outliving
        that is the difference between a settings page that works and one that
        needs the service stopped and started by hand afterwards.
        """
        while not _stopping:
            try:
                self.serve()
            except Exception as failure:
                if _stopping:
                    break
                print('lost LCDd: %s' % failure, file=sys.stderr)
            finally:
                self.panel.close()

            for _ in range(50):
                if _stopping:
                    break
                time.sleep(0.1)


def _on_term(signum, frame):
    global _stopping
    _stopping = True


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def display_size(options):
    """The display geometry, preferring what the driver actually reported."""
    fallback = config.geometry(options['size']) or (16, 2)
    panel = Panel()
    try:
        panel.open(CLIENT_NAME + '-size', timeout=2.0)
        size = (panel.width, panel.height) if panel.width and panel.height else fallback
    except (OSError, IOError):
        size = fallback
    finally:
        panel.close()
    return size


def probe():
    """Ask LCDd what it is, without drawing anything.

    A client that adds no screen changes nothing on the glass, so this is safe
    to call while somebody is watching the panel - which is exactly when the
    status page is open.
    """
    panel = Panel()
    try:
        greeting = panel.open(CLIENT_NAME + '-probe', timeout=2.0)
    except (OSError, IOError) as failure:
        return {'answering': False, 'error': str(failure)}
    finally:
        panel.close()

    return {
        'answering': True,
        'version': panel.version,
        'protocol': panel.protocol,
        'width': panel.width,
        'height': panel.height,
        'greeting': greeting,
    }


def start():
    """Build the configuration, start LCDd, then start the screen client."""
    options = config.settings()
    if not options['enabled']:
        return {'status': 'error',
                'message': 'The front panel is switched off. Turn it on under '
                           'System > Front Panel and save before starting it.'}

    built = config.build(options)
    if built.get('status') != 'ok':
        return built

    ensure_dirs()

    # A speed that changed is a speed LCDd already read and is not using. It
    # only reads the file once, at startup, so honouring the new setting means
    # letting the old process go - which is what the settings page asks for
    # when it saves, whether it calls this start or restart.
    if built['changed'] and running(LCDD_PID):
        stop()

    if not running(LCDD_PID):
        rotate(LCDD_LOG)
        failure = spawn([DAEMON,
                         # -f first: it is what lets this call return before the
                         # thing it started has finished. See spawn().
                         '-f',
                         '-t', 'frontpanel-LCDd',
                         '-P', LCDD_SUPERVISOR,
                         '-p', LCDD_PID,
                         '-o', LCDD_LOG,
                         # newsyslog rotates this file and signals the supervisor
                         # named in the pidfile. -H is what makes that signal mean
                         # "close this file and open it again"; without it the
                         # supervisor would take SIGHUP as the end of its day.
                         '-H',
                         '-m', '3',
                         LCDD, '-f', '-c', config.LCDD_CONF], 'LCDd')
        if failure:
            return {'status': 'error', 'message': failure}

        deadline = time.monotonic() + STARTUP_SECONDS
        answer = probe()
        while not answer['answering'] and time.monotonic() < deadline:
            time.sleep(0.4)
            answer = probe()

        if not answer['answering']:
            return {'status': 'error',
                    'message': 'LCDd did not open its socket within %d seconds. What it '
                               'said while trying is below.' % STARTUP_SECONDS,
                    'log': log_tail(LCDD_LOG, 12)}

    if not running(CLIENT_PID):
        failure = start_client()
        if failure:
            return {'status': 'error', 'message': failure}

    log('started on %s with the %s driver' % (built['device'] or 'no device', built['driver']))
    answer = status()
    answer['config'] = built
    return answer


def stop():
    """Stop the client first, then LCDd.

    In that order on purpose: the client is what has screens on the glass, and
    letting it go first means LCDd tears down an empty display rather than one
    that is still being written to.
    """
    notes = []
    for supervisor, child, name in ((CLIENT_SUPERVISOR, CLIENT_PID, 'the screen client'),
                                    (LCDD_SUPERVISOR, LCDD_PID, 'LCDd')):
        message = terminate(supervisor, child, name)
        if message:
            notes.append(message)

    answer = {'status': 'ok', 'stopped': True}
    if notes:
        answer['notes'] = notes
    log('stopped')
    return answer


def restart():
    stop()
    return start()


def status():
    """Everything a person or a page needs to know at a glance."""
    options = config.settings()
    device = options['device']
    taken, getty = (config.getty_on(device) if device else (False, {}))

    answer = {
        'status': 'ok',
        'enabled': options['enabled'],
        'driver': options['driver'],
        'device': {
            'path': device,
            'present': bool(device) and os.path.exists(device),
            'getty': taken,
            'ttys': getty,
        },
        'config': {
            'path': config.LCDD_CONF,
            'exists': os.path.exists(config.LCDD_CONF),
            'written': int(os.path.getmtime(config.LCDD_CONF))
                       if os.path.exists(config.LCDD_CONF) else None,
        },
        'lcdd': {
            'running': bool(running(LCDD_PID)),
            'pid': running(LCDD_PID),
            'log': LCDD_LOG,
        },
        'client': {
            'running': bool(running(CLIENT_PID)),
            'pid': running(CLIENT_PID),
            'log': CLIENT_LOG,
        },
        'panel': probe(),
        'keys': keypad.report(options),
    }

    complaints = log_tail(LCDD_LOG, 6, only_errors=True)
    if complaints:
        answer['lcdd']['complaints'] = complaints

    answer['running'] = answer['lcdd']['running'] and answer['client']['running']
    return answer


def test(text='', seconds=5):
    """Write one line to the panel, then take it back.

    The line is the caller's where they wrote one - the settings page has a box
    for it - and the plugin's own where they did not, because somebody who only
    wants to know whether the panel answers should not have to invent words
    first. The second row carries the time either way: a clock that moved is
    the proof that what is on the glass arrived just now rather than an hour
    ago.

    The screen is raised to `alert` so it outranks the rotation, and given a
    timeout of its own in eighths of a second so that even if this process is
    killed in the middle of the test the panel returns to normal by itself.
    """
    seconds = max(1, min(30, int(seconds)))

    panel = Panel()
    try:
        panel.open(CLIENT_NAME + '-test', timeout=3.0)
    except (OSError, IOError) as failure:
        panel.close()
        return {'status': 'error',
                'message': 'The panel is not running, so there is nothing to write to '
                           '(%s). Start it first.' % failure}

    width = panel.width or (config.geometry(config.settings()['size']) or (16, 2))[0]
    lines = [screens.cut(text if text else 'Front Panel', width),
             screens.cut('test %s' % time.strftime('%H:%M:%S'), width)]

    try:
        panel.send('screen_add %s' % TEST_SCREEN)
        panel.send('screen_set %s -name %s -priority alert -duration %d -timeout %d'
                   % (TEST_SCREEN, quoted('test'), seconds * 8, (seconds + 2) * 8))
        panel.send('widget_add %s l1 string' % TEST_SCREEN)
        panel.send('widget_add %s l2 string' % TEST_SCREEN)
        panel.send('widget_set %s l1 1 1 %s' % (TEST_SCREEN, quoted(lines[0])))
        panel.send('widget_set %s l2 1 2 %s' % (TEST_SCREEN, quoted(lines[1])))

        refusals = [line for line in panel.drain(1.0) if line.startswith('huh?')]
        time.sleep(seconds)
        panel.send('screen_del %s' % TEST_SCREEN)
        refusals += [line for line in panel.drain(0.5) if line.startswith('huh?')]
    except (OSError, IOError) as failure:
        panel.close()
        return {'status': 'error', 'message': 'LCDd went away during the test: %s' % failure}
    finally:
        panel.close()

    answer = {'status': 'ok', 'lines': lines, 'seconds': seconds,
              'width': panel.width, 'height': panel.height}
    if refusals:
        answer['status'] = 'error'
        answer['message'] = 'LCDd refused part of the test: %s' % '; '.join(refusals)
    return answer


def start_client():
    """Start the screen client, assuming LCDd is already up."""
    return spawn([DAEMON,
                  '-f',   # as for LCDd: without it this call waits for the client
                  '-t', 'frontpanel-client',
                  '-P', CLIENT_SUPERVISOR,
                  '-p', CLIENT_PID,
                  '-o', CLIENT_LOG,
                  '-H',   # as above: newsyslog's SIGHUP reopens the file
                  '-m', '3',
                  PYTHON, os.path.join(HERE, 'frontpanel.py'), 'client'],
                 'the screen client')


def learn(seconds=20):
    """Find out which button is which, by asking somebody to press one.

    Measuring this panel's key map by hand took four rounds of "press that one
    three times and I will read the log". This is the same procedure with the
    log file and the round trips taken out, and it obeys the rule that made the
    hand measurement work at all: the screen feeder is stopped first.

    At 2400 baud the display and the keypad share one line. With screens
    changing every three seconds two thirds of the presses were lost; with the
    screen quiet, every one arrived. So this stops the feeder, writes one line
    to the panel and then says nothing more until the time is up.

    What it reports is the matrix position, not just the name. The name is only
    whatever LCDd.conf currently calls that position - on the reference panel
    the driver's default map called the down arrow "Enter" - so the position is
    the part that is actually a fact about the hardware. keys.py finds it two
    ways and says which: the driver writes the position out itself where the
    log holds that line, and where it does not, the map that was written for
    this panel is read backwards, which names the row the press came from
    because that is the table the driver used to name it in the first place.
    """
    seconds = max(3, min(120, int(seconds)))
    options = config.settings()

    if not options['keypad']:
        return {'status': 'error',
                'message': 'The keypad is switched off in the settings, so nothing is '
                           'polling the keys. Turn it on and save first.'}

    answer = probe()
    if not answer['answering']:
        return {'status': 'error',
                'message': 'The panel is not running, so there is nothing to listen to. '
                           'Start it first.'}

    level = keypad.log_level()
    if level is not None and level < config.REPORT_LEVEL_KEYS:
        return {'status': 'error',
                'message': 'LCDd is writing its log at report level %d, and it does not '
                           'name a key at all below level %d - so a press would arrive '
                           'and leave nothing here to read. Save the settings with the '
                           'keypad switched on and restart the panel, which is what asks '
                           'LCDd for that level.' % (level, config.REPORT_LEVEL_KEYS)}

    # Stop the feeder, and remember whether it was ours to put back.
    feeding = bool(running(CLIENT_PID))
    if feeding:
        terminate(CLIENT_SUPERVISOR, CLIENT_PID, 'the screen client')

    panel = Panel()
    seen = []
    try:
        panel.open(CLIENT_NAME + '-learn', timeout=3.0)
        width = panel.width or (config.geometry(options['size']) or (16, 2))[0]

        panel.send('screen_add %s' % LEARN_SCREEN)
        panel.send('screen_set %s -name %s -priority input -timeout %d'
                   % (LEARN_SCREEN, quoted('learn'), (seconds + 5) * 8))
        panel.send('widget_add %s l1 string' % LEARN_SCREEN)
        panel.send('widget_add %s l2 string' % LEARN_SCREEN)
        panel.send('widget_set %s l1 1 1 %s'
                   % (LEARN_SCREEN, quoted(screens.cut('Press a button', width))))
        panel.send('widget_set %s l2 1 2 %s'
                   % (LEARN_SCREEN, quoted(screens.cut('listening %ds' % seconds, width))))

        # From here on the panel is not written to again. Everything below is a
        # file being read.
        offset = keypad.size(LCDD_LOG)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            arrived, offset = keypad.events(LCDD_LOG, offset)
            for event in arrived:
                if event not in seen:
                    seen.append(event)
                try:
                    keypad.record_press(event['key'])
                except Exception:
                    pass
            if seen:
                break
            time.sleep(0.2)

        panel.send('screen_del %s' % LEARN_SCREEN)
    except (OSError, IOError) as failure:
        return {'status': 'error', 'message': 'LCDd went away while listening: %s' % failure}
    finally:
        panel.close()
        if feeding:
            start_client()

    return {
        'status': 'ok',
        'seconds': seconds,
        'seen': seen,
        'heard': bool(seen),
        'feeder_stopped': feeding,
        'note': ('' if seen else
                 'Nothing arrived. The keys are polled rather than volunteered, so a '
                 'panel whose driver cannot read them stays silent however long you '
                 'listen - which is itself an answer worth having.'),
    }


def screens_now():
    """What every screen would show at this moment, for the GUI preview."""
    options = config.settings()
    width, height = display_size(options)
    return {
        'status': 'ok',
        'width': width,
        'height': height,
        'screens': screens.catalogue(width, height, options),
    }


def panels():
    """The appliance table, joined to what this machine says it is.

    The match is a proposal and is labelled as one. Nothing here applies it -
    the settings page offers it and the owner presses Apply, because a wrong
    driver writing to the wrong serial port is not a mistake a plugin should
    make on its own initiative.
    """
    table = config.load_panels()
    fields = config.smbios()
    key, entry = config.match_panel(table, fields)

    ports = []
    for device in config.serial_devices():
        taken, detail = config.getty_on(device)
        # `ttys` is the line out of /etc/ttys, as a line, because that is what
        # the settings page puts under the port for somebody to check against
        # the file. The parts it was read as are handed over too, under a name
        # of their own, rather than one field trying to be both and arriving on
        # the page as the word "object".
        ports.append({
            'device': device,
            'getty': taken,
            'ttys': detail.get('line', ''),
            'ttys_detail': detail,
        })

    return {
        'status': 'ok',
        'smbios': fields,
        'match': key,
        'matched': key != 'generic',
        'panel': entry,
        'confirmed': bool(entry.get('confirmed')),
        'drivers': config.installed_drivers(),
        'devices': ports,
    }


def diagnostics():
    """The two reports the settings page reads side by side, in one answer.

    They are written separately and stay separate here - what the keys have
    done, and what this machine looks like from the outside - because the page
    shows them in two boxes and reads each from under its own name. Asking for
    them together is not only one round trip instead of two: it means the key
    counts and the list of serial ports on that page describe the same second.
    """
    return {
        'status': 'ok',
        'keys': keypad.report(),
        'panels': panels(),
    }


def main(argv):
    command = argv[1] if len(argv) > 1 else 'status'

    if command == 'client':
        signal.signal(signal.SIGTERM, _on_term)
        signal.signal(signal.SIGINT, _on_term)
        ensure_dirs()
        Client(config.settings()).run()
        return 0

    handlers = {
        'build-config': lambda: config.build(),
        'start': start,
        'stop': stop,
        'restart': restart,
        'status': status,
        'screens': screens_now,
        'keys': lambda: keypad.report(),
        'learn': lambda: learn(argv[2] if len(argv) > 2 and argv[2] else 20),
        'panels': panels,
        'diagnostics': diagnostics,
        # The text is whatever the settings page put in the box, and an empty
        # box is a perfectly good request: test() has a line of its own for it.
        'test': lambda: test(argv[2] if len(argv) > 2 else ''),
    }

    handler = handlers.get(command)
    if handler is None:
        print(json.dumps({'status': 'error', 'message': 'unknown command: %s' % command}))
        return 1

    try:
        answer = handler()
    except Exception as failure:
        # The answer is the point of pressing the button, so it is printed even
        # when it is bad news, and the non-zero exit is left for the shell.
        print(json.dumps({'status': 'error', 'message': str(failure)}))
        return 1

    print(json.dumps(answer))
    return 0 if answer.get('status') == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
