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

    Turns the plugin's settings into an LCDd.conf, and refuses when it should.

    Every adjustable speed on the settings page is a real LCDproc option, not a
    number this plugin interprets for itself:

        screen_seconds   -> [server] WaitTime        how long each screen shows
        scroll_speed     -> [server] TitleSpeed      how fast a long title moves
        heartbeat        -> [server] Heartbeat       the blinking glyph, on or off
        bus_delay        -> [<driver>] DelayMult     the delay multiplier
        refresh_seconds  -> [<driver>] RefreshDisplay full redraw interval

    The last two belong to the driver, and most drivers have never heard of
    them: writing DelayMult into a [mtc_s16209x] section makes LCDd complain on
    every start. So the option names each driver really accepts are read out of
    /usr/local/etc/LCDd.conf.sample - the file the lcdproc package installs -
    rather than remembered in a table here, and a knob the driver cannot use is
    left out and reported instead of written and hoped for.

    Two refusals matter more than the rest, and both check rather than assume:

      * a device that is not there. A path under /dev that does not exist, or
        exists as something other than a character device, is a typing mistake
        or a port that was removed, and writing a config for it only moves the
        failure into LCDd's log where nobody reads it.

      * a device that /etc/ttys gives a getty. That is somebody's console. The
        check is not "is it named like a console": it reads /etc/ttys, finds
        the line for this port, and - because a port marked `onifconsole` only
        gets a getty when it IS the console - asks the kernel which ports the
        console actually uses before deciding. On the reference machine
        /dev/cuau1 is `onifconsole` and the console is ttyu0, so the port is
        free, and this module has to be able to say so rather than refuse
        everything that carries a getty line.

    The file is written to a temporary name in its own directory and renamed
    over the old one, so a reader - LCDd starting at that exact moment - sees
    either the whole old file or the whole new one and never half of either.
    An identical file is not rewritten at all: the reference machine has spent
    31% of its disk's write endurance, and a settings page that saves without
    changing anything should cost nothing.
"""

import json
import os
import re
import shlex
import stat
import subprocess
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))

CONFIG_XML = '/conf/config.xml'
MODEL = './OPNsense/FrontPanel'
GENERAL = MODEL + '/general'
KEYGRID = MODEL + '/keys'

CONF_DIR = '/usr/local/etc/frontpanel'
LCDD_CONF = os.path.join(CONF_DIR, 'LCDd.conf')

DRIVER_DIR = '/usr/local/lib/lcdproc'
SAMPLE = '/usr/local/etc/LCDd.conf.sample'
TTYS = '/etc/ttys'

# LCDd listens here. Loopback only: the panel is a local device and there is no
# reason for anything off this machine to be able to draw on it.
BIND = '127.0.0.1'
PORT = 13666

# What LCDd will say about itself.
#
# 2 is LCDd's own default and means warnings and errors; 3 adds the notices that
# name the configuration file it read and the clients that connected, which is
# what somebody opening this log after a failed start actually wants.
#
# 4 is where the server writes one line per keystroke - "Driver [hd44780]
# generated keystroke Down" - and that line is the whole of what keys.py counts,
# so switching the keypad on costs exactly one level more.
#
# It stops there on purpose. Level 5 adds LCDd's debug narration, and that
# includes screenlist_process() once per frame: at the server's eight frames a
# second, something like 700,000 lines a day. Measured here on 2026-09-21 with a
# throwaway LCDd on the text driver: eight seconds at level 5 wrote 65 of those
# lines, level 4 wrote none, and both named every keystroke. A log growing that
# fast is rotated away within minutes, and it takes the key history the settings
# page reads with it - so the chattiest level would cost us the very evidence it
# was asked for.
REPORT_LEVEL = 3
REPORT_LEVEL_KEYS = 4

# Ranges. Every one of these is either documented in LCDd.conf.sample or is a
# plain sanity bound; nothing here is a guess about what the hardware likes.
LIMITS = {
    'screen_seconds': (1, 60, 3),     # WaitTime, seconds; sample default is 4
    'scroll_speed': (0, 10, 10),      # TitleSpeed, sample says "legal: 0-10"
    'bus_delay': (1, 20, 2),          # DelayMult; 2 is what this panel settled on
    'refresh_seconds': (0, 60, 4),    # RefreshDisplay; 0 turns the redraw off
}

DEFAULTS = {
    'enabled': False,
    'driver': '',
    'connection': '',
    'device': '',
    'size': '16x2',
    'keypad': True,
    'screen_seconds': LIMITS['screen_seconds'][2],
    'scroll_speed': LIMITS['scroll_speed'][2],
    'bus_delay': LIMITS['bus_delay'][2],
    'refresh_seconds': LIMITS['refresh_seconds'][2],
    'heartbeat': False,
    'screens': 'identity,wan,throughput,system,temperature,ports,message',
    'message': '',
    'throughput_if': '',
    'keys': [],
}

_SIZE = re.compile(r'^\s*(\d{1,3})\s*[xX]\s*(\d{1,3})\s*$')

# "4,1" or "4_1" - a matrix position as the owner would write it.
_POSITION = re.compile(r'^\s*(\d{1,2})\s*[,_ ]\s*(\d{1,2})\s*$')

# What may appear on the right of an "=" in LCDd.conf. Deliberately narrow:
# every value this plugin writes is a device path, a size, a number or a key
# name, and none of those needs anything else.
_VALUE = re.compile(r'^[A-Za-z0-9 ,._/:+-]+$')

# The option names that carry a key map. These are the one kind of option the
# sample configuration cannot be asked about: it documents the four positions
# its own example panel happens to have, so a panel whose keys sit anywhere else
# would have its map dropped by a check that trusted that list. See emit().
_KEY_OPTION = re.compile(r'^Key(?:Matrix_\d{1,2}_\d{1,2}|Direct_\d{1,3})$')


def _run(args):
    """Run a command and return its stdout, or '' if it failed.

    Same habit as the rest of the author's plugins: a tool that is missing or
    unhappy must never take the caller down with it, it must show up as absent
    data that the caller can talk about.
    """
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return done.stdout if done.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def load_panels():
    with open(os.path.join(HERE, 'panels.json'), 'r') as handle:
        return json.load(handle)


def smbios():
    """What the machine says it is, the same way os-linkhealth asks."""
    values = {}
    for line in _run(['/bin/kenv']).splitlines():
        if line.startswith('smbios.'):
            key, _, value = line.partition('=')
            values[key.strip()] = value.strip().strip('"')
    return {
        'maker': values.get('smbios.planar.maker') or values.get('smbios.system.maker', ''),
        'product': values.get('smbios.planar.product') or values.get('smbios.system.product', ''),
        'version': values.get('smbios.planar.version') or values.get('smbios.system.version', ''),
    }


def match_panel(table=None, fields=None):
    """The appliance entry for this machine, and the key it is filed under.

    Returns ('generic', entry) when nothing matches. The caller is expected to
    treat every entry as a proposal: nothing in this module applies one.
    """
    table = table if table is not None else load_panels()
    panels = table.get('panels') or {}
    fields = fields if fields is not None else smbios()

    for key, entry in panels.items():
        if key == 'generic':
            continue
        criteria = entry.get('match') or {}
        if not criteria:
            continue
        if all(re.search(pattern, fields.get(field, '') or '')
               for field, pattern in criteria.items()):
            return key, entry

    return 'generic', panels.get('generic', {})


def installed_drivers():
    """The drivers this installation of LCDproc actually carries.

    Offered to the settings page so the list is what is on the disk rather than
    what LCDproc ships somewhere else. 36 of them on the reference machine.
    """
    try:
        names = [name[:-3] for name in os.listdir(DRIVER_DIR) if name.endswith('.so')]
    except OSError:
        return []
    return sorted(names, key=str.lower)


def serial_devices():
    """The callout serial ports this machine has.

    /dev/cua* is the callout side; the .init and .lock nodes beside each one
    are settings, not ports, and must not be offered as somewhere to write.
    """
    found = []
    try:
        for name in os.listdir('/dev'):
            if not name.startswith('cua') or name.endswith(('.init', '.lock')):
                continue
            found.append('/dev/' + name)
    except OSError:
        return []
    return sorted(found)


def driver_options(driver, table=None):
    """Option names the given driver understands, or None when unknown.

    Read from the sample configuration the lcdproc package installs, because
    that file is versioned with the drivers themselves. The table in
    panels.json is only used when the sample is not there, and None - "we do
    not know this driver's options" - is a real answer that the caller reports
    rather than a reason to refuse.
    """
    section = _sample_section(driver)
    if section is not None:
        return section

    table = table if table is not None else load_panels()
    listed = (table.get('drivers') or {}).get(driver)
    return set(listed) if isinstance(listed, list) else None


def _sample_section(driver):
    """Option names under [<driver>] in LCDd.conf.sample, or None."""
    try:
        with open(SAMPLE, 'r', errors='replace') as handle:
            text = handle.read()
    except OSError:
        return None

    wanted = None
    options = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('['):
            name = stripped[1:].split(']', 1)[0]
            wanted = (name == driver)
            continue
        if not wanted:
            continue
        # Commented-out options count: the sample documents most options with a
        # leading '#', and an option is no less real for being a default.
        candidate = stripped[1:].strip() if stripped.startswith('#') else stripped
        match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=', candidate)
        if match:
            options.add(match.group(1))

    return options or None


def console_ports():
    """The tty names the kernel is currently using as a console.

    kern.console reads like "ttyu0,ttyv0,/ttyu0,ucom,ttyv0," - the active list,
    a slash, then everything available. Only the active list decides whether an
    `onifconsole` getty is running, so the tail is dropped.
    """
    raw = _run(['/sbin/sysctl', '-n', 'kern.console']).strip()
    active = raw.split('/', 1)[0]
    return {name for name in (part.strip() for part in active.split(',')) if name}


def tty_name(device):
    """The /etc/ttys name for a device node under /dev.

    /dev/cuau1 is the callout side of the port whose dial-in side - and whose
    /etc/ttys line - is ttyu1. They are the same piece of hardware, so a getty
    on ttyu1 is a getty on the port we were asked to write to.
    """
    base = os.path.basename(device or '')
    if base.startswith('cua'):
        return 'tty' + base[3:]
    return base


def getty_on(device):
    """Whether /etc/ttys runs a getty on this port, and the line that says so.

    Returns (running, detail). detail is filled in whenever a line for the port
    exists at all, so a caller can explain the refusal - or explain why it did
    not refuse - in words the owner can check against the file.
    """
    name = tty_name(device)
    if not name:
        return False, {}

    try:
        with open(TTYS, 'r', errors='replace') as handle:
            lines = handle.read().splitlines()
    except OSError:
        # No /etc/ttys is not a reason to claim a port. We cannot prove it is
        # free, so we say so and let the caller decide; the caller refuses.
        return True, {'name': name, 'reason': 'unreadable', 'file': TTYS}

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        try:
            fields = shlex.split(stripped)
        except ValueError:
            fields = stripped.split()
        if not fields or fields[0] != name:
            continue

        command = fields[1] if len(fields) > 1 else ''
        flags = [field.lower() for field in fields[3:]] if len(fields) > 3 else []
        detail = {'name': name, 'command': command, 'flags': flags, 'line': stripped}

        if not command or command.lower() == 'none':
            return False, detail
        if 'off' in flags:
            return False, detail
        if 'onifconsole' in flags:
            consoles = console_ports()
            detail['consoles'] = sorted(consoles)
            # The distinction this whole function exists for: `onifconsole`
            # only starts a getty when this port is the console. On the
            # reference machine it is not - the console is ttyu0 - so the panel
            # port is free and must not be refused.
            return name in consoles, detail
        if 'on' in flags:
            return True, detail
        return False, detail

    return False, {'name': name, 'reason': 'absent', 'file': TTYS}


def _clamp(name, value):
    low, high, fallback = LIMITS[name]
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def matrix_option(position):
    """"4,1" -> "KeyMatrix_4_1", or '' when it is not a matrix position.

    The position column belongs to the hardware and is the one thing on the
    key grid nobody may edit, so anything that is not two small numbers is
    dropped rather than written into LCDd.conf as a guess.
    """
    match = _POSITION.match(position or '')
    if not match:
        return ''
    return 'KeyMatrix_%s_%s' % (match.group(1), match.group(2))


def key_rows(root):
    """The key grid from the configuration: one row per matrix position.

    Three of the four columns are the owner's - the label printed on their own
    metal, the name LCDd is told to call the key, and what the plugin does when
    it arrives. Only the position is the hardware's.
    """
    rows = []
    section = root.find(KEYGRID)
    if section is None:
        return rows

    for node in section:
        position = (node.findtext('position') or '').strip()
        if not matrix_option(position):
            continue
        rows.append({
            'position': position.replace('_', ',').replace(' ', ''),
            'label': (node.findtext('label') or '').strip(),
            'key': (node.findtext('key') or '').strip(),
            'action': (node.findtext('action') or '').strip(),
            'target': (node.findtext('target') or '').strip(),
        })

    rows.sort(key=lambda row: row['position'])
    return rows


def key_map(options, panel):
    """The keys LCDd will be told this panel has, and where the map came from.

    Three possible sources, and the settings page is expected to say which one
    it is looking at. A map that was measured on somebody else's appliance is
    not a fact about this one, and LCDproc's own defaults for this connection
    type are a worse guess still: they put Enter where this panel has its down
    arrow, which is how a panel ends up scrolling the wrong way.
    """
    chosen = {}
    for row in options.get('keys') or []:
        name = matrix_option(row['position'])
        if name and row.get('key'):
            chosen[name] = row['key']
    if chosen:
        return chosen, 'settings'

    shipped = dict((panel or {}).get('keymap') or {})
    if shipped:
        return shipped, 'panels.json'

    # Nothing to say. The driver's own defaults then apply, and build() reports
    # that plainly rather than letting the page imply somebody measured them.
    return {}, 'driver defaults'


def settings(root=None):
    """The plugin's settings, with the shipped defaults behind every one.

    Written so a fresh installation answers sensibly before anybody has opened
    the settings page: an absent field is not an error, it is the default. The
    one thing that is never defaulted is which port to write to - see build().
    """
    values = dict(DEFAULTS)
    values['keys'] = []

    if root is None:
        try:
            root = ET.parse(CONFIG_XML).getroot()
        except Exception:
            return values

    values['keys'] = key_rows(root)

    general = root.find(GENERAL)
    if general is None:
        return values

    def text(name, default=None):
        found = general.findtext(name)
        return found if found not in (None, '') else default

    values['enabled'] = text('enabled', '0') == '1'
    values['keypad'] = text('keypad', '1') == '1'
    values['heartbeat'] = text('heartbeat', '0') == '1'

    for name in ('driver', 'connection', 'device', 'size', 'screens', 'message', 'throughput_if'):
        found = text(name)
        if found is not None:
            values[name] = found.strip()

    for name in ('screen_seconds', 'scroll_speed', 'bus_delay', 'refresh_seconds'):
        values[name] = _clamp(name, text(name, DEFAULTS[name]))

    if not values['size']:
        values['size'] = DEFAULTS['size']

    return values


def geometry(size):
    """(columns, rows) from a "16x2" string, or None when it is not one."""
    match = _SIZE.match(size or '')
    if not match:
        return None
    columns, rows = int(match.group(1)), int(match.group(2))
    if columns < 1 or rows < 1:
        return None
    return columns, rows


def render(options, panel=None, known=None):
    """The text of LCDd.conf for these settings, and an account of it.

    Returns (text, report). The report carries:

        dropped   speed knobs this driver has no option for, so the settings
                  page can say "this driver ignores the bus delay" rather than
                  showing a slider that does nothing;
        refused   options whose value was not something we are willing to write
                  into a configuration file at all;
        keymap    the key map that was written and where it came from, because
                  a page that shows a key map owes the reader that much.
    """
    driver = options['driver']
    panel = panel or {}
    dropped = []
    refused = []

    lines = [
        '# Generated by os-frontpanel. Edits are lost the next time a setting',
        '# changes on System > Front Panel; change it there instead.',
        '',
        '[server]',
        'DriverPath=%s/' % DRIVER_DIR.rstrip('/'),
        'Driver=%s' % driver,
        'Bind=%s' % BIND,
        'Port=%d' % PORT,
        'User=nobody',
        'ReportToSyslog=no',
        # The key test reads LCDd's log, and LCDd names a key there only from
        # level 4 upwards, so that level is asked for when - and only when - the
        # keypad is switched on. Not a level higher: see REPORT_LEVEL_KEYS.
        'ReportLevel=%d' % (REPORT_LEVEL_KEYS if options['keypad'] else REPORT_LEVEL),
        # Our own screens are the point of the plugin. LCDproc's built-in
        # information screen would otherwise show the client count to somebody
        # walking past a rack.
        #
        # 'blank' and not 'off', and the difference is not the one the names
        # suggest. LCDd.conf.sample: 'off' makes the server screen a background
        # screen, "only visible when no other screens are active"; 'blank' is
        # the same except that what it shows then is nothing at all. So 'off'
        # does not switch that screen off - it switches off its turn in the
        # rotation and leaves it as the thing the panel falls back to, which is
        # precisely the moment somebody would see it: after LCDd starts and
        # before our client has connected, and again after the client exits
        # while LCDd is still being stopped. 'blank' leaves the panel dark in
        # both, which is what the rest of this plugin promises.
        'ServerScreen=blank',
        'AutoRotate=on',
        '',
        '# how long each screen is shown, in seconds',
        'WaitTime=%d' % options['screen_seconds'],
        '# how fast a line too long for the display scrolls, 0-10',
        'TitleSpeed=%d' % options['scroll_speed'],
        # 'on' forces the glyph onto every screen, 'open' lets a client ask for
        # it. Nothing here ever asks, so 'open' would mean "never" and say the
        # opposite of what the setting is called.
        '# the blinking glyph; some panels draw it as a solid block',
        'Heartbeat=%s' % ('on' if options['heartbeat'] else 'off'),
        '',
        # What LCDd writes on the glass by itself, at each end of its life. Left
        # alone it has a built-in pair, and the second one is the problem: a
        # stopped panel is not a dark panel, it is a panel holding the last
        # thing written to it, and LCDd's last words are "Thanks for using
        # LCDproc!". Measured here on 2026-09-21, on a throwaway server: that is
        # exactly what a SIGTERM leaves behind, and on this appliance it would
        # sit on the front of the rack until somebody started the panel again -
        # every stop, every uninstall, and for a moment in the middle of every
        # settings change. Two lines of spaces instead, which is the clearing
        # the rc script and the installer both promise; the width does not have
        # to match the display, because the frame is cleared before they are
        # drawn. The greeting goes the same way: this panel belongs to the
        # firewall, and the few seconds before the first screen arrives are not
        # LCDproc's to advertise in.
        '# what LCDd shows before our first screen and after our last',
        'Hello="                "',
        'Hello="                "',
        'GoodBye="                "',
        'GoodBye="                "',
        '',
        # LCDd acts on a key no client has claimed, and its own default for
        # that is ToggleRotateKey=Enter - so one press of a key the feeder has
        # let slip would stop the rotation with nothing on the panel to say
        # why. These three names are deliberately ones no driver produces, and
        # every key this plugin cares about is therefore handled in one place:
        # the feeder, where the settings page can reach it.
        '# keys are the plugin\'s to act on, never the server\'s',
        'ToggleRotateKey=FrontPanelNoRotate',
        'PrevScreenKey=FrontPanelNoPrev',
        'NextScreenKey=FrontPanelNoNext',
        '',
        # The same argument, for the other half of the server that reads keys.
        # LCDproc carries a menu of its own - a client living inside the server -
        # and LCDd.conf.sample gives it Escape to open, Enter to choose and Up and
        # Down to move: every key this appliance has. It only ever sees a press no
        # client has claimed, which sounds harmless, and mostly is: while one of
        # our screens is on the glass the key comes to us instead. But the test
        # line, the key test and every minute the feeder is not running are
        # precisely when it is not, and LCDproc's menu arriving on the panel then
        # is a thing nobody asked for, that the panel does not explain, and that
        # the four buttons in front of a confused owner cannot obviously leave.
        # Four names no driver produces, and the menu stays where it belongs.
        '[menu]',
        '# LCDproc\'s own menu, pointed at keys this panel will never report',
        'MenuKey=FrontPanelNoMenu',
        'EnterKey=FrontPanelNoEnter',
        'UpKey=FrontPanelNoUp',
        'DownKey=FrontPanelNoDown',
        '',
        '[%s]' % driver,
    ]

    def emit(name, value, comment=None):
        """Write a driver option, but only one the driver admits to having.

        The value is checked as well as the name. Most of what lands here came
        from a form: a newline inside one of those fields would end the line
        and start a new setting, and the next setting in an LCDd.conf is
        allowed to say User=root or point the driver at a different port. One
        narrow pattern is cheaper than trusting every field on the page.
        """
        if known is not None and name not in known:
            # One exception, and it is the key map. The sample lists the four
            # positions its example hd44780 happens to use - KeyMatrix_4_1 to
            # _4_4, which is this appliance's four and nobody else's guarantee -
            # so a panel with a key at 3,2 would have that row quietly thrown
            # away by a check that treated the sample as the complete list. The
            # driver accepts any KeyMatrix_row_column it is handed, so the shape
            # of the name is what is checked; a driver that cannot read a key at
            # all has no Keypad option, and render() refuses the map outright
            # rather than writing it here.
            if not (_KEY_OPTION.match(name) and 'Keypad' in known):
                return False
        text = str(value).strip()
        if not _VALUE.match(text):
            refused.append(name)
            return False
        if comment:
            lines.append('# ' + comment)
        lines.append('%s=%s' % (name, text))
        return True

    # The panel entry's own options first - ConnectionType and anything else a
    # confirmed appliance needs - then the settings page's answers on top,
    # because the owner's choice outranks the table's proposal.
    for name, value in sorted((panel.get('options') or {}).items()):
        if name in ('Device', 'Size', 'Keypad'):
            continue  # these come from the settings below, not from the table
        if name == 'ConnectionType' and options['connection']:
            continue  # ditto: the page holds the chosen connection
        emit(name, value)

    if options['connection']:
        emit('ConnectionType', options['connection'])

    if options['device']:
        emit('Device', options['device'])
    emit('Size', options['size'])
    emit('Keypad', 'yes' if options['keypad'] else 'no')

    mapped, source = key_map(options, panel)
    if not options['keypad']:
        mapped, source = {}, 'the keypad is off'
    elif mapped and known is not None and 'Keypad' not in known:
        # A driver with no Keypad option cannot read a button, whatever map it is
        # given - mtc_s16209x lights this shape of screen and can never do more.
        # Writing the map anyway would leave the settings page showing a key
        # table for a panel that will never speak, so it is dropped and said.
        dropped.append('the key map')
        mapped, source = {}, 'this driver cannot read keys'
    else:
        for name in sorted(mapped):
            emit(name, mapped[name])

    if not emit('DelayMult', options['bus_delay'],
                'raise this if characters go missing on the way to the panel'):
        dropped.append('bus_delay')
    if not emit('RefreshDisplay', options['refresh_seconds'],
                'redraw everything this often, so corruption cannot persist'):
        dropped.append('refresh_seconds')

    # Not on the settings page, and deliberately so: DelayBus is what the
    # delay multiplier multiplies, and a keep-alive of a couple of seconds is
    # what stops a panel that has been idle from being assumed to be awake.
    # Both were part of the configuration that was proven on this machine.
    emit('DelayBus', 'yes')
    emit('KeepAliveDisplay', 2)

    report = {
        'dropped': dropped,
        'refused': refused,
        'keymap': {'source': source, 'map': mapped},
    }
    return '\n'.join(lines) + '\n', report


def write_atomic(path, text, mode=0o640):
    """Write the file in one step, so a reader never sees half of it.

    A temporary name in the same directory, flushed to the disk, then renamed
    over the target: rename within one filesystem is atomic, so LCDd starting
    at that instant opens either the whole old file or the whole new one.
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o755, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, prefix='.LCDd.conf-')
    try:
        with os.fdopen(handle, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        # os.replace rather than os.rename: both are rename(2) here, but this
        # one says out loud that an existing file is meant to be replaced.
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _refuse(message, field=''):
    answer = {'status': 'error', 'message': message}
    if field:
        answer['field'] = field
    return answer


def build(options=None, path=LCDD_CONF):
    """Write LCDd.conf for the current settings, or explain why we will not.

    Every refusal names the setting it is about, so the settings page can put
    the message beside the field rather than at the top of the form.
    """
    table = load_panels()
    options = options if options is not None else settings()
    _, panel = match_panel(table)

    driver = options['driver']
    if not driver:
        return _refuse('No driver chosen. The settings page lists the drivers this '
                       'installation of LCDproc carries, and offers the one this '
                       'appliance is known to use.', 'driver')

    available = installed_drivers()
    if available and driver not in available:
        return _refuse('LCDproc here has no driver called "%s". Installed: %s.'
                       % (driver, ', '.join(available)), 'driver')

    known = driver_options(driver, table)

    size = options['size']
    if geometry(size) is None:
        return _refuse('"%s" is not a display size. Write it as columns x rows, '
                       'for example 16x2.' % size, 'size')

    device = options['device']
    needs_device = known is None or 'Device' in known
    if needs_device and not device:
        return _refuse('No serial port chosen. The settings page lists the ports this '
                       'machine has; on this appliance the panel is on the second one.',
                       'device')

    if device:
        if not os.path.exists(device):
            return _refuse('There is no %s on this machine. The settings page lists the '
                           'ports that exist: %s.'
                           % (device, ', '.join(serial_devices()) or 'none found'), 'device')
        try:
            if not stat.S_ISCHR(os.stat(device).st_mode):
                return _refuse('%s is not a serial port - it is an ordinary file or a '
                               'directory. Nothing will be written to it.' % device, 'device')
        except OSError as failure:
            return _refuse('%s cannot be examined: %s' % (device, failure), 'device')

        taken, detail = getty_on(device)
        if taken:
            if detail.get('reason') == 'unreadable':
                return _refuse('%s cannot be read, so whether %s carries a login prompt '
                               'cannot be checked. A panel is not worth taking somebody\'s '
                               'console away on a guess.' % (TTYS, device), 'device')
            return _refuse('%s carries a login prompt: %s says "%s". That is a console, and '
                           'this plugin will not write over one. Turn the getty off in %s '
                           'first, or choose another port.'
                           % (device, TTYS, detail.get('line', ''), TTYS), 'device')

    text, report = render(options, panel, known)
    dropped, refused, keymap = report['dropped'], report['refused'], report['keymap']

    previous = None
    try:
        with open(path, 'r') as handle:
            previous = handle.read()
    except OSError:
        previous = None

    if previous == text:
        changed = False
    else:
        write_atomic(path, text)
        changed = True

    answer = {
        'status': 'ok',
        'path': path,
        'changed': changed,
        'driver': driver,
        'device': device,
        'size': size,
        'keypad': options['keypad'],
        'keymap': keymap,
        'dropped': dropped,
        'refused': refused,
        'options_checked': known is not None,
    }

    notes = []
    if options['keypad'] and keymap['source'] == 'driver defaults':
        notes.append('No key map was written, so the %s driver\'s own defaults apply. Those '
                     'are a guess about this panel, not a measurement of it: use the key '
                     'test to find out which button is which.' % driver)
    if dropped:
        notes.append('The %s driver has no option for: %s. Those settings were left out '
                     'rather than written into a section that would reject them.'
                     % (driver, ', '.join(dropped)))
    if refused:
        notes.append('These settings held characters that have no business in a '
                     'configuration file and were not written: %s. Check them on the '
                     'settings page.' % ', '.join(refused))
    if known is None:
        notes.append('The option names for the %s driver could not be checked - %s is not '
                     'installed and this driver is not in panels.json - so the settings '
                     'were written as given. Watch LCDd\'s log on the next start.'
                     % (driver, SAMPLE))
    if notes:
        answer['notes'] = notes

    return answer
