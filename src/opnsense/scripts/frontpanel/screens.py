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

    What the panel says, one small generator per screen.

    Each screen is a function that returns two lines already cut to the width
    of the display, or None when it has nothing to say on this machine. None is
    a real answer: the temperature screen does not exist on a board with no
    sensor, and the ports screen does not exist where os-linkhealth is not
    installed. A screen that cannot say anything true is absent rather than
    blank, and the rotation simply skips it.

    Two rules shape every line here.

    Sixteen columns is the whole budget. There is no room for a label and a
    value on the same line unless both are short, so each screen decides for
    itself where the label goes - "WAN ok 14ms" over the address is readable,
    "WAN 192.168.70." is not - and nothing is ever allowed to run off the end.

    The panel's character ROM is not Unicode. An HD44780 draws the ASCII range
    and a handful of symbols, so text arriving from the configuration - a
    hostname, an interface description, the owner's own message - is folded
    down to ASCII before it is sent. The GUI is used in Arabic and the panel
    cannot draw a single Arabic letter; rather than quietly dropping the text,
    the fold leaves a '?' per character and the preview shows both versions so
    the owner sees what will really appear on the metal.

    Nothing in this module writes to the disk. The two screens that need a rate
    rather than a total - throughput and CPU - keep their previous sample in
    memory, and when there is no previous sample (a one-shot call from the GUI)
    they take a second one a fraction of a second later. The reference machine
    has spent 31% of its disk's write endurance and a screen refreshing every
    couple of seconds is not worth any of the rest of it.
"""

import glob
import json
import re
import socket
import subprocess
import time
import unicodedata
import xml.etree.ElementTree as ET

CONFIG_XML = '/conf/config.xml'

# The one and only thing this plugin reads from os-linkhealth: a status
# document, read-only, and entirely optional. If it is not there the ports
# screen does not exist and nothing else changes.
LINKHEALTH_STATUS = '/var/db/linkhealth/status.json'

# dpinger is what OPNsense uses to decide whether a gateway answers. Its socket
# is the live answer; /tmp/gateways.status is the cache the GUI reads and is
# used only when no socket is there to ask.
DPINGER_SOCKETS = '/var/run/dpinger_*.sock'
GATEWAY_STATUS = '/tmp/gateways.status'

# How stale a kept sample may be before a rate computed from it stops meaning
# anything. The screen client refreshes every couple of seconds, so it never
# reaches this; a one-shot call from the GUI always does.
SAMPLE_MAX_AGE = 30
SAMPLE_GAP = 0.4

# os-linkhealth's own severity order, repeated here rather than imported: the
# two plugins do not depend on each other, and a copied constant is a much
# smaller price than a dependency.
VERDICT_ORDER = {'ok': 0, 'idle': 0, 'down': 0, 'disabled': 0, 'info': 0,
                 'watch': 1, 'warn': 2, 'fail': 3}

_LAST = {'cpu': None, 'net': {}}

_BOOTTIME = re.compile(r'sec\s*=\s*(\d+)')
_TEMPERATURE = re.compile(r'^(-?\d+(?:\.\d+)?)C?$')


def _run(args):
    """Run a command and return its stdout, or '' if it failed."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return done.stdout if done.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def _sysctl(*names):
    """Values for the named sysctls as {name: string}, missing ones absent.

    One call for the lot: asking four times costs four process launches for an
    answer the kernel hands over in one.
    """
    values = {}
    for line in _run(['/sbin/sysctl', '-e'] + list(names)).splitlines():
        name, _, value = line.partition('=')
        if name:
            values[name.strip()] = value.strip()
    return values


def _sysctl_tree(prefix):
    """Every sysctl under a prefix as {name: string}."""
    values = {}
    for line in _run(['/sbin/sysctl', '-e', prefix]).splitlines():
        name, _, value = line.partition('=')
        if name.startswith(prefix):
            values[name.strip()] = value.strip()
    return values


def fold(text):
    """Fold text down to what an HD44780-class panel can actually draw.

    Accented Latin loses its accent, because a panel that can draw 'e' should
    show 'e' rather than a question mark. Everything outside ASCII after that -
    Arabic, CJK, emoji - becomes '?', which is honest: the character was asked
    for and the hardware has no glyph for it.
    """
    if not text:
        return ''
    # NFKD splits an accented letter into the letter and a combining mark;
    # dropping the marks is what turns "Ubersicht" with an umlaut into plain
    # "Ubersicht" instead of "U?bersicht". It also quietly removes Arabic
    # vowel marks, which no panel of this class could draw either.
    flattened = unicodedata.normalize('NFKD', str(text))
    stripped = ''.join(char for char in flattened if not unicodedata.combining(char))
    plain = stripped.encode('ascii', 'replace').decode('ascii')
    # Control characters would be drawn as whatever happens to live at that
    # code point in the panel's ROM, which on this one is a Japanese kana.
    return ''.join(char if 0x20 <= ord(char) < 0x7f else ' ' for char in plain)


def cut(text, width):
    """One line, folded and cut to the display width."""
    return fold(text)[:max(0, int(width))]


def _bits(value):
    """A bit rate in as few characters as a 16-column line can spare."""
    value = max(0.0, float(value))
    for suffix, scale in (('G', 1e9), ('M', 1e6), ('k', 1e3)):
        if value >= scale:
            scaled = value / scale
            return '%.1f%s' % (scaled, suffix) if scaled < 10 else '%d%s' % (round(scaled), suffix)
    return '%d' % round(value)


def _uptime(seconds):
    """Uptime in the shortest form that stays unambiguous."""
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return '%dd %02d:%02d' % (days, hours, minutes)
    return '%02d:%02d:%02d' % (hours, minutes, rest % 60)


def interfaces():
    """{role: {'if': device, 'descr': name}} from the configuration.

    The configuration rather than the kernel's interface description, for the
    reason os-linkhealth gives at greater length: after a rename the kernel
    keeps the old string, and the configuration is what the operator edited.
    """
    found = {}
    try:
        root = ET.parse(CONFIG_XML).getroot()
    except Exception:
        return found

    section = root.find('interfaces')
    if section is None:
        return found

    for node in section:
        device = node.findtext('if')
        if not device:
            continue
        found[node.tag] = {
            'if': device.strip(),
            'descr': (node.findtext('descr') or '').strip(),
        }
    return found


def address(device):
    """The first IPv4 address on an interface, or '' when it has none.

    IPv4 only, and not because IPv6 does not matter: a v6 address does not fit
    on a sixteen-column line in any form that could be read from a rack, and
    half an address is worse than none.
    """
    if not device:
        return ''
    for line in _run(['/sbin/ifconfig', device, 'inet']).splitlines():
        fields = line.split()
        if fields and fields[0] == 'inet':
            return fields[1]
    return ''


def default_gateway_name():
    """The name of the default gateway in the configuration, or ''."""
    try:
        root = ET.parse(CONFIG_XML).getroot()
    except Exception:
        return ''

    section = root.find('gateways')
    if section is None:
        return ''

    first = ''
    for node in section.findall('gateway_item'):
        name = (node.findtext('name') or '').strip()
        if not name:
            continue
        first = first or name
        if (node.findtext('defaultgw') or '') == '1':
            return name
    return first


def gateway():
    """What the default gateway is doing, as far as dpinger will say.

    Returns {'name', 'rtt_ms', 'loss', 'state'} or None when this firewall has
    no monitored gateway at all. state is 'up', 'loss', 'down', or 'unknown' -
    the last meaning dpinger is watching the gateway but has nothing to report
    yet, which is not the same thing as a gateway that does not answer.
    """
    wanted = default_gateway_name()
    answers = {}

    for path in sorted(glob.glob(DPINGER_SOCKETS)):
        try:
            stream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            stream.settimeout(2)
            stream.connect(path)
            raw = stream.recv(256).decode('ascii', 'replace').strip()
            stream.close()
        except (OSError, socket.error):
            continue

        # "WAN_1G_DHCP 14077 2137 0" - name, round trip and its deviation in
        # microseconds, then loss as a whole percentage.
        fields = raw.split()
        if len(fields) < 4:
            continue
        try:
            answers[fields[0]] = {
                'name': fields[0],
                'rtt_ms': int(fields[1]) / 1000.0,
                'loss': int(fields[3]),
            }
        except ValueError:
            continue

    chosen = answers.get(wanted) or (answers[sorted(answers)[0]] if answers else None)

    if chosen is not None:
        if chosen['loss'] >= 100:
            chosen['state'] = 'down'
        elif chosen['rtt_ms'] <= 0:
            # Nothing has come back yet. dpinger answers with three zeroes in
            # the seconds after it starts - before its first reply, and again
            # after the interface it watches is rebuilt - and a gateway that is
            # genuinely unreachable says so by its loss reaching 100 instead.
            # Printing DOWN on the front of a firewall because a daemon has not
            # finished its first round trip is a false alarm on the one screen
            # somebody would walk across a room to read.
            chosen['state'] = 'unknown'
        elif chosen['loss'] > 0:
            chosen['state'] = 'loss'
        else:
            chosen['state'] = 'up'
        return chosen

    # No socket to ask. OPNsense keeps the last verdict in a small serialised
    # PHP array; "none" there means no fault was found.
    try:
        with open(GATEWAY_STATUS, 'r', errors='replace') as handle:
            blob = handle.read()
    except OSError:
        return None

    pairs = re.findall(r's:\d+:"([^"]*)";s:\d+:"([^"]*)";', blob)
    if not pairs:
        return None
    table = dict(pairs)
    name = wanted if wanted in table else pairs[0][0]
    verdict = (table.get(name) or '').lower()
    return {
        'name': name,
        'rtt_ms': 0.0,
        'loss': 0,
        'state': 'up' if verdict in ('none', '') else ('down' if 'down' in verdict else 'loss'),
    }


def _cp_time():
    """(total ticks, idle ticks) from kern.cp_time."""
    raw = _sysctl('kern.cp_time').get('kern.cp_time', '')
    parts = [int(value) for value in raw.split() if value.lstrip('-').isdigit()]
    if len(parts) < 5:
        return None
    return sum(parts), parts[4]


def cpu_busy():
    """Percentage of CPU time that was not idle, over the last sample gap.

    The kernel counts ticks since boot, so a single reading says what the
    machine has averaged since it started - which is never what somebody
    standing in front of it wants to know. Two readings are needed, and the
    previous one is kept in memory between refreshes.
    """
    now = time.time()
    sample = _cp_time()
    if sample is None:
        return None

    kept = _LAST['cpu']
    if kept is None or now - kept[0] > SAMPLE_MAX_AGE:
        time.sleep(SAMPLE_GAP)
        second = _cp_time()
        if second is None:
            # A reading that failed is not a reading. Keeping it would leave
            # the next call within the half minute subtracting from nothing,
            # and this screen would vanish from the rotation - as a screen with
            # nothing to say - until the memory aged out.
            _LAST['cpu'] = None
            return None
        _LAST['cpu'] = (time.time(), second)
        kept = (now, sample)
        sample = second
    else:
        _LAST['cpu'] = (now, sample)

    total = sample[0] - kept[1][0]
    idle = sample[1] - kept[1][1]
    if total <= 0 or idle < 0:
        return None
    return max(0.0, min(100.0, 100.0 * (total - idle) / total))


def memory_used():
    """Percentage of physical memory in use, the way top(1) would count it."""
    values = _sysctl('hw.physmem', 'hw.pagesize',
                     'vm.stats.vm.v_free_count',
                     'vm.stats.vm.v_inactive_count',
                     'vm.stats.vm.v_cache_count')
    try:
        physical = int(values['hw.physmem'])
        page = int(values['hw.pagesize'])
    except (KeyError, ValueError):
        return None
    if physical <= 0 or page <= 0:
        return None

    spare = 0
    for name in ('vm.stats.vm.v_free_count', 'vm.stats.vm.v_inactive_count',
                 'vm.stats.vm.v_cache_count'):
        try:
            spare += int(values.get(name, 0))
        except ValueError:
            continue

    used = physical - spare * page
    return max(0.0, min(100.0, 100.0 * used / physical))


def uptime_seconds():
    raw = _sysctl('kern.boottime').get('kern.boottime', '')
    match = _BOOTTIME.search(raw)
    if not match:
        return None
    return max(0, int(time.time()) - int(match.group(1)))


def _netstat(device):
    """(rx bytes, tx bytes) for one interface, from its link-level row.

    `netstat -i -b -n -W` prints the link row first and then one row per
    address, repeating the name with no counters on it. Only the link row -
    the one whose Network column starts with "<Link" - carries the totals.

    The counters are counted from the right hand end, and that is the whole
    trick: the eight numbers after the address are always the same eight, in
    the same order, ending with Coll, while the Address column itself is empty
    on an interface that has no hardware address at all. Counting from the left
    on such a row reads Opkts as the bytes received and is out by a factor of
    fifty without anything looking wrong. Measured here on 2026-09-21: twelve
    columns on igb0, Ibytes fifth from the end and Obytes second.
    """
    text = _run(['/usr/bin/netstat', '-i', '-b', '-n', '-W', '-I', device])
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 11 or fields[0] != device:
            continue
        if not fields[2].startswith('<Link'):
            continue
        try:
            return int(fields[-5]), int(fields[-2])
        except ValueError:
            return None
    return None


def throughput_rate(device):
    """(bits in per second, bits out per second) for an interface."""
    now = time.time()
    sample = _netstat(device)
    if sample is None:
        return None

    kept = _LAST['net'].get(device)
    if kept is None or now - kept[0] > SAMPLE_MAX_AGE:
        time.sleep(SAMPLE_GAP)
        second = _netstat(device)
        later = time.time()
        if second is None:
            # Same as the processor screen: a failed read is forgotten rather
            # than remembered, so the next call takes two fresh samples instead
            # of trying to subtract from one that was never taken.
            _LAST['net'].pop(device, None)
            return None
        _LAST['net'][device] = (later, second)
        kept = (now, sample)
        sample = second
        elapsed = later - now
    else:
        elapsed = now - kept[0]
        _LAST['net'][device] = (now, sample)

    if elapsed <= 0:
        return None

    received = sample[0] - kept[1][0]
    sent = sample[1] - kept[1][1]
    if received < 0 or sent < 0:
        return None  # the counters wrapped or the interface was reset
    return received * 8 / elapsed, sent * 8 / elapsed


def temperatures():
    """Every temperature the board offers, in Celsius, grouped by what it is."""
    readings = {'cpu': [], 'board': [], 'zone': []}

    for name, value in _sysctl_tree('dev.cpu').items():
        if name.endswith('.temperature'):
            number = _celsius(value)
            if number is not None:
                readings['cpu'].append(number)

    for name, value in _sysctl_tree('dev.pchtherm').items():
        if name.endswith('.temperature'):
            number = _celsius(value)
            if number is not None:
                readings['board'].append(number)

    for name, value in _sysctl_tree('hw.acpi.thermal').items():
        if name.endswith('.temperature'):
            number = _celsius(value)
            if number is not None:
                readings['zone'].append(number)

    return readings


def _celsius(raw):
    """A temperature sysctl as a number. `sysctl -e` prints them as "61.0C"."""
    match = _TEMPERATURE.match((raw or '').strip())
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def linkhealth_status():
    """os-linkhealth's status document, or None.

    Read-only, and its absence is not a failure of any kind: this is the whole
    of the relationship between the two plugins.
    """
    try:
        with open(LINKHEALTH_STATUS, 'r') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# The screens themselves. Each takes the display geometry and the plugin's
# settings, and returns two finished lines or None.
# ---------------------------------------------------------------------------

def identity(width, height, options):
    """Which firewall this is, and where to find it."""
    host = _run(['/bin/hostname']).strip() or 'OPNsense'
    # The short name, not the fully qualified one: "OPNsense.internal" is
    # already at the edge of sixteen columns and the domain is the part nobody
    # standing at the rack needs.
    short = host.split('.', 1)[0]

    table = interfaces()
    lan = (table.get('lan') or {}).get('if', '')
    found = address(lan)

    return [cut(short, width),
            cut('LAN ' + found if found else 'LAN no address', width)]


def wan(width, height, options):
    """The address the world sees, and whether the gateway answers."""
    table = interfaces()
    device = (table.get('wan') or {}).get('if', '')
    found = address(device)
    state = gateway()

    if state is None:
        verdict = 'no gateway'
    elif state['state'] == 'down':
        verdict = 'DOWN'
    elif state['state'] == 'unknown':
        # Being watched, with nothing measured yet. Sixteen columns exactly.
        verdict = 'no reply yet'
    elif state['state'] == 'loss':
        verdict = '%d%% loss' % state['loss']
    elif state['rtt_ms'] > 0:
        verdict = 'ok %dms' % round(state['rtt_ms'])
    else:
        verdict = 'ok'

    # The label goes on the line with the verdict because both are short. The
    # address gets a line to itself, which is the only way it fits whole.
    return [cut('WAN ' + verdict, width),
            cut(found if found else 'no address', width)]


def throughput(width, height, options):
    """How much is moving, on the interface the owner picked."""
    table = interfaces()
    device = (options.get('throughput_if') or '').strip()
    role = ''

    if not device:
        # Nothing chosen: the WAN is the interface whose rate somebody watching
        # a firewall's front panel almost always means.
        device = (table.get('wan') or {}).get('if', '')
        role = 'wan'

    if not device:
        return None

    for name, entry in table.items():
        if entry.get('if') == device:
            role = role or name
            label = entry.get('descr') or name.upper()
            break
    else:
        label = device

    rate = throughput_rate(device)
    if rate is None:
        return [cut(label, width), cut('%s: no counters' % device, width)]

    incoming, outgoing = rate
    return [cut(label, width),
            cut('Rx%s Tx%s' % (_bits(incoming), _bits(outgoing)), width)]


def system(width, height, options):
    """What the machine is doing with itself."""
    busy = cpu_busy()
    used = memory_used()
    running = uptime_seconds()

    first = 'CPU%s MEM%s' % (
        '%3d%%' % round(busy) if busy is not None else '  ?',
        '%3d%%' % round(used) if used is not None else '  ?')

    second = 'up %s' % _uptime(running) if running is not None else 'uptime unknown'
    return [cut(first, width), cut(second, width)]


def temperature(width, height, options):
    """The CPU sensor, where one exists - and nothing at all where none does."""
    readings = temperatures()
    cores = readings['cpu']
    if not cores:
        return None

    first = 'CPU %dC max %dC' % (round(sum(cores) / len(cores)), round(max(cores)))

    others = []
    if readings['board']:
        others.append('brd %dC' % round(max(readings['board'])))
    if readings['zone']:
        others.append('sys %dC' % round(max(readings['zone'])))

    second = '  '.join(others) if others else '%d cores' % len(cores)
    return [cut(first, width), cut(second, width)]


def ports(width, height, options):
    """The worst port os-linkhealth can see, or nothing when it is not here.

    This screen is the entire contact between the two plugins: one file, read
    if it happens to exist, and simply absent when it does not.
    """
    status = linkhealth_status()
    if not status:
        return None

    watched = [port for port in status.get('ports') or []
               if (port.get('verdict') or {}).get('state') != 'disabled']
    if not watched:
        return None

    def severity(port):
        verdict = port.get('verdict') or {}
        return (VERDICT_ORDER.get(verdict.get('state', 'ok'), 0),
                (port.get('window') or {}).get('error_ppm', 0))

    worst = max(watched, key=severity)
    verdict = worst.get('verdict') or {}
    state = verdict.get('state', 'ok')

    if VERDICT_ORDER.get(state, 0) == 0:
        # os-linkhealth calls a port with a cable in it and a negotiated speed
        # "active"; "down" is a port that is up but unplugged.
        up = sum(1 for port in watched
                 if (port.get('link') or {}).get('state') == 'active')
        return [cut('Ports OK', width),
                cut('%d of %d linked' % (up, len(watched)), width)]

    label = worst.get('label') or worst.get('if') or '?'
    shown = state.upper()
    first = '%s %s' % (cut(label, max(1, width - len(shown) - 1)), shown)

    ppm = (worst.get('window') or {}).get('error_ppm', 0)
    if ppm:
        # Parts per million is the right unit for the counter and the wrong one
        # for a rack. 38000 ppm is 3.8 frames in a hundred, which is a number a
        # person can act on.
        second = '%.1f%% bad frames' % (ppm / 10000.0)
    else:
        reasons = verdict.get('reasons') or []
        second = reasons[0].get('text', state) if reasons else state

    return [cut(first, width), cut(second, width)]


def message(width, height, options):
    """A fixed line the owner writes, for a rack somebody else walks past."""
    text = (options.get('message') or '').strip()
    if not text:
        return None

    folded = fold(text)
    if len(folded) <= width:
        return [folded, '']

    # Break at a space when there is one in the right region, so a two-word
    # message is not split through the middle of a word.
    head = folded[:width]
    space = head.rfind(' ')
    if space >= width // 2:
        return [head[:space].rstrip(), cut(folded[space + 1:], width)]
    return [head, cut(folded[width:], width)]


# Order matters: this is the order the screens rotate in unless the settings
# name a different one.
SCREENS = [
    ('identity', 'Identity', identity),
    ('wan', 'WAN', wan),
    ('throughput', 'Throughput', throughput),
    ('system', 'System', system),
    ('temperature', 'Temperature', temperature),
    ('ports', 'Ports', ports),
    ('message', 'Message', message),
]

BY_KEY = {key: (title, function) for key, title, function in SCREENS}


def chosen(options):
    """The screen keys the settings ask for, in the order they ask for them.

    An unknown name is ignored rather than refused: a setting written by a
    newer version of the plugin must not stop an older one from drawing
    anything at all.
    """
    raw = (options.get('screens') or '').strip()
    if not raw:
        return [key for key, _, _ in SCREENS]

    wanted = []
    for name in re.split(r'[,\s]+', raw):
        name = name.strip()
        if name in BY_KEY and name not in wanted:
            wanted.append(name)
    return wanted


def render(key, width, height, options):
    """One screen's finished lines, or None when it has nothing to say."""
    entry = BY_KEY.get(key)
    if entry is None:
        return None

    try:
        lines = entry[1](width, height, options)
    except Exception:
        # A screen that throws must not take the panel down with it. The others
        # keep rotating and this one is simply absent until it works again.
        return None

    if not lines:
        return None

    lines = [cut(line, width) for line in lines][:2]
    while len(lines) < 2:
        lines.append('')
    return lines


def catalogue(width, height, options, only=None):
    """Every screen, with what it would show right now - the GUI's preview.

    `source` appears beside the lines only when folding to ASCII changed the
    text, which is how the settings page can warn that the panel has no glyph
    for what the owner typed.
    """
    wanted = chosen(options) if only is None else only
    listed = []

    for key, title, _ in SCREENS:
        lines = render(key, width, height, options)
        entry = {
            'key': key,
            'title': title,
            'enabled': key in wanted,
            'available': lines is not None,
            'lines': lines or [],
        }

        if key == 'message' and lines is not None:
            raw = (options.get('message') or '').strip()
            if fold(raw) != raw:
                entry['source'] = raw
                entry['note'] = 'the panel has no glyph for some of these characters'

        if lines is None:
            entry['reason'] = _absence(key)

        listed.append(entry)

    listed.sort(key=lambda item: (wanted.index(item['key']) if item['key'] in wanted
                                  else len(wanted) + [k for k, _, _ in SCREENS].index(item['key'])))
    return listed


def _absence(key):
    """Why a screen has nothing to say, in words worth showing a person."""
    if key == 'ports':
        return ('os-linkhealth is not installed, or has not written %s yet'
                % LINKHEALTH_STATUS)
    if key == 'temperature':
        return 'this board reports no CPU temperature'
    if key == 'message':
        return 'no message has been written'
    if key == 'throughput':
        return 'no interface chosen and no WAN configured'
    return 'nothing to show on this machine'
