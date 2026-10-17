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

    The panel's menu, laid out the way the vendor's firmware lays out its own
    on this hardware (the menu file of the XGS 3300's original firmware, read
    off the appliance): a main menu of lists the keys walk through, each entry
    either opening another list, showing two lines, or doing something.

        System    date, uptime, processor and memory, load, disk, version,
                  temperature
        Network   every assigned interface with its address and link, the
                  default gateway
        Screens   the rotation's screens - choosing one holds it on the glass
        Power     reboot and shutdown, when the settings allow them

    Reboot and shutdown sit behind the same two-step confirmation as there: the
    entry opens a list whose first line does nothing and whose second line is
    the confirmation, so a single stray press can never reach it - it takes
    Enter, a step down, and Enter again.

    Four roles move through it - up, down, select and back - and frontpanel.py
    decides which key plays which. Nothing here writes to the panel; a press
    goes in and comes back as what to show, or what to do.
"""

import os
import subprocess
import syslog
import time

import screens


class Item(object):
    """One line of a list: a list of its own, two lines to show, or an action."""

    def __init__(self, title, children=None, show=None, act=None):
        self.title = title
        self.children = children
        self.show = show
        self.act = act


def _lines(first, second):
    return [first, second]


def _uptime():
    seconds = screens.uptime_seconds()
    return _lines('Uptime', screens._uptime(seconds) if seconds is not None else 'unknown')


def _load():
    try:
        one, five, fifteen = os.getloadavg()
    except OSError:
        return _lines('Load average', 'unknown')
    return _lines('Load average', '%.2f %.2f %.2f' % (one, five, fifteen))


def _disk():
    try:
        st = os.statvfs('/')
    except OSError:
        return _lines('Disk /', 'unknown')
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    if total <= 0:
        return _lines('Disk /', 'unknown')
    used = 100.0 * (total - free) / total
    return _lines('Disk /', '%d%% of %dG' % (round(used), round(total / 1e9)))


def _version():
    try:
        out = subprocess.run(['/usr/local/sbin/opnsense-version', '-v'], capture_output=True,
                             text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ''
    return _lines('OPNsense', out or 'unknown')


def _interface(info):
    """An assigned interface: its name over its address, or why there is none."""
    def show():
        device = info['if']
        status = ''
        for line in screens._run(['/sbin/ifconfig', device]).splitlines():
            line = line.strip()
            if line.startswith('status:'):
                status = line.split(':', 1)[1].strip()
        address = screens.address(device)
        name = '%s %s' % (info['descr'] or device, device) if info['descr'] else device
        if address:
            second = address
        elif status and status != 'active':
            second = 'link down'
        else:
            second = 'no address'
        return _lines(name, second)
    return show


def _gateway():
    found = screens.gateway()
    if not found:
        return _lines('Gateway', 'none monitored')
    rtt = found.get('rtt_ms')
    state = found.get('state') or 'unknown'
    return _lines('GW %s' % (found.get('name') or ''),
                  state + (' %dms' % round(rtt) if isinstance(rtt, (int, float)) else ''))


def tree(options, width, order, ring=False):
    """The menu for this installation: `order` is the rotation's screens, as shown.

    `ring` is a panel drawn as a ring of cells (bridge.Direct), which gets an
    entry for lining its text up with the arrow keys.
    """
    def screen(key):
        return lambda: screens.render(key, width, 2, options) or _lines(key, 'nothing to show')

    system = [
        Item('Date and time', show=lambda: _lines(time.strftime('%Y-%m-%d'), time.strftime('%H:%M:%S'))),
        Item('Uptime', show=_uptime),
        Item('CPU and memory', show=screen('system')),
        Item('Load average', show=_load),
        Item('Disk', show=_disk),
        Item('Version', show=_version),
        Item('Temperature', show=screen('temperature')),
    ]
    if ring:
        system.append(Item('Align the text', act=('align',)))

    network = []
    for role, info in sorted(screens.interfaces().items()):
        network.append(Item(info['descr'] or role.upper(), show=_interface(info)))
    network.append(Item('Gateway', show=_gateway))

    rotation = [Item(screens.BY_KEY.get(key, (key,))[0], act=('pin', key)) for key in order]

    main = [
        Item('System', children=system),
        Item('Network', children=network),
        Item('Screens', children=rotation or [Item('none')]),
    ]
    if options.get('power', True):
        main.append(Item('Power', children=[
            Item('Reboot', children=[Item(' v to continue'), Item('Confirm reboot?', act=('reboot',))]),
            Item('Shutdown', children=[Item(' v to continue'), Item('Confirm shutdown?', act=('halt',))]),
        ]))
    return Item('Main menu', children=main)


class Menu(object):
    """Where somebody is in the menu, and what a press does there."""

    def __init__(self, root, width):
        self.width = width
        self.stack = [(root, 0)]    # (list, index of the highlighted entry)
        self.showing = None         # two lines of an entry being shown, or None

    def _current(self):
        return self.stack[-1]

    def lines(self):
        if self.showing is not None:
            return [screens.cut(line, self.width) for line in self.showing[:2]]
        node, index = self._current()
        children = node.children or []
        head = '%s %d/%d' % (node.title, index + 1, len(children))
        title = children[index].title if children else ''
        return [screens.cut(head, self.width), screens.cut('> ' + title, self.width)]

    def press(self, role):
        """Move, open, show or act. Returns None, ('close',), ('pin', key), ('align',), ('reboot',) or ('halt',)."""
        node, index = self._current()
        children = node.children or []

        if self.showing is not None:
            # On an entry's two lines: back returns to its list, up and down step to the next one
            # and show it, select reads it again.
            if role == 'back':
                self.showing = None
                return None
            if role in ('up', 'down') and children:
                index = (index + (-1 if role == 'up' else 1)) % len(children)
                self.stack[-1] = (node, index)
                entry = children[index]
                if entry.show is None:
                    self.showing = None
                    return None
            entry = children[index]
            self.showing = entry.show() if entry.show else None
            return None

        if role == 'up' and children:
            self.stack[-1] = (node, (index - 1) % len(children))
        elif role == 'down' and children:
            self.stack[-1] = (node, (index + 1) % len(children))
        elif role == 'back':
            if len(self.stack) == 1:
                return ('close',)
            self.stack.pop()
        elif role == 'select' and children:
            entry = children[index]
            if entry.children is not None:
                self.stack.append((entry, 0))
            elif entry.show is not None:
                self.showing = entry.show()
            elif entry.act is not None:
                return entry.act
        return None


def power(action):
    """Reboot or halt through configd, the way the GUI's own buttons do, and say who asked."""
    syslog.openlog('frontpanel', syslog.LOG_PID, syslog.LOG_DAEMON)
    syslog.syslog(syslog.LOG_WARNING, '%s requested from the front panel' %
                  ('reboot' if action == 'reboot' else 'shutdown'))
    syslog.closelog()
    subprocess.Popen(['/usr/local/sbin/configctl', 'system', 'reboot' if action == 'reboot' else 'halt'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
