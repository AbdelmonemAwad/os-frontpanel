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

    Whether the buttons beside the panel do anything, and how we know.

    The four keys are polled, never volunteered: the host sends a poll byte and
    the panel answers with a key code. Nothing arrives by listening, which is
    why a passive probe on the reference machine saw nothing for a long time
    and why the plugin treats keys as an enhancement rather than a requirement.

    A user on unknown hardware should be able to find out in ten seconds rather
    than guessing, so this module answers one question - "has this panel ever
    reported a press, and which one?" - from the two places an answer can come
    from.

      * LCDd's own log. The server reports a keystroke the moment the driver
        produces one, and it does so whatever the key was later used for. This
        is the only source that sees a press on a key no client has reserved.
        It costs something: LCDd names a key in its log only from report level 4
        upwards, so the generated configuration asks for that level while the
        keypad is switched on - and asks for no more than that, because level 5
        adds a line per frame and would rotate this whole history away inside a
        few minutes. The log is started fresh every time the service starts,
        which is what makes "since it started" a true statement rather than a
        hopeful one.

      * The screen client's own record. When a key the client reserved arrives,
        it writes the press down here. That is the strongest evidence there is:
        not "the driver saw an edge on a wire" but "a key press reached a
        program and made the panel do something".

    Both are reported, separately and by name, because they prove different
    things and a settings page that blurred them would be lying by omission.

    Neither source names the *matrix position*, which is the one thing somebody
    on unknown hardware actually needs. Over the socket LCDd says `key Enter`,
    and that is not a fact about the panel - it is whatever LCDd.conf currently
    calls the position that spoke. On the reference appliance those two
    disagreed: LCDproc's default map for this connection type puts `Enter` at
    4,1, where the panel has its down arrow.

    So the position is recovered twice over, and the answer says which way.

      * The hd44780 driver writes it out itself - "Key pressed: Down (4,1)" -
        and where that line is in the log it is read straight off, because it
        comes from the driver's own scan of the wires.

      * Where it is not, the map is read back out of the generated LCDd.conf and
        inverted. That is exact rather than clever: the driver turned a position
        into a name using precisely that table, so the name it produced names
        the row that produced it. The one ambiguity is a map that gave two
        positions the same name, and that is reported as the two positions it
        is rather than as a guess between them.

    One more thing measured on that appliance, and the reason the learn mode
    stops the screen feeder before it listens: at 2400 baud the display and the
    keypad share one line, and writing starves polling. With screens changing
    every three seconds, two thirds of the presses were lost. With the screen
    quiet, every one arrived.
"""

import json
import os
import re
import time

import config

LOG = '/var/log/frontpanel/LCDd.log'
RECORD = '/var/db/frontpanel/keys.json'

# Enough of the tail to hold a long evening of presses without reading a log
# that has been running for a month.
TAIL_BYTES = 256 * 1024

# How many presses the client's record keeps. The counts are kept for ever;
# only the individual timestamps are trimmed.
KEEP_PRESSES = 50

# "Driver [hd44780] generated keystroke Enter" - written for every driver, and
# the line that actually proves a key arrived at the server.
_KEYSTROKE = re.compile(r'generated keystroke\s+(\S+)')

# "HD44780_get_key: Key pressed: Enter (4,1)" - hd44780 only, but it names the
# matrix position, which is what somebody wiring up an unknown panel needs.
_MATRIX = re.compile(r'Key pressed:\s+(\S+)\s+\((\d+),(\d+)\)')

# "KeyMatrix_4_1=Down" in the generated configuration: the table the driver used
# to turn a position into the name the log then printed. Read back, it says
# which position a name came from - see configured_map().
_KEY_LINE = re.compile(r'^KeyMatrix_(\d{1,2})_(\d{1,2})\s*=\s*(\S+)\s*$')

# What the feeder does when a key arrives. These are the plugin's own doing,
# not LCDd's: the generated configuration deliberately points the server's
# three built-in key bindings at names no driver produces, so that everything
# a button does is decided here and can be changed from the settings page
# without restarting anything.
ACTIONS = ('next', 'previous', 'menu', 'back', 'screen', 'backlight', 'none')

# Behind an empty key grid, the map this plugin was written against: the panel
# is printed with a down arrow, ESC, an up arrow and ENTER, in that order.
DEFAULT_ACTIONS = {
    'Down': 'next',
    'Up': 'previous',
    'Enter': 'menu',
    'Escape': 'back',
}


def actions_for(options):
    """{key name: (action, target)} for this installation.

    The key grid wins where it has an opinion. Where it has none - a fresh
    installation, or a row the owner left blank - the defaults above apply, so
    the buttons do something sensible before anybody has configured them.
    """
    table = {}
    for row in options.get('keys') or []:
        name = (row.get('key') or '').strip()
        action = (row.get('action') or '').strip()
        if not name or action not in ACTIONS:
            continue
        table[name] = (action, (row.get('target') or '').strip())

    for name, action in DEFAULT_ACTIONS.items():
        table.setdefault(name, (action, ''))
    return table


def size(path=LOG):
    """How long the log is now, so a later read can start from here."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def events(path=LOG, offset=0):
    """Key presses written to the log since `offset`, and the new offset.

    This is what the learn mode reads. It returns the matrix position as well
    as the name, because on an unmeasured panel the position is the answer:
    the name is only whatever LCDd.conf currently calls that position, and
    finding out that the two disagree is the entire point of the exercise.

    A log that has become shorter than the offset was rotated underneath us -
    `start` does exactly that - so reading begins again from nothing.
    """
    now = size(path)
    if now < offset:
        offset = 0

    try:
        with open(path, 'r', errors='replace') as handle:
            handle.seek(offset)
            text = handle.read()
            offset = handle.tell()
    except OSError:
        return [], offset

    found = []
    position = {}
    mapped = configured_map()
    for line in text.splitlines():
        match = _MATRIX.search(line)
        if match:
            position[match.group(1)] = '%s,%s' % (match.group(2), match.group(3))
            continue
        match = _KEYSTROKE.search(line)
        if match:
            name = match.group(1)
            where, source = place(name, position, mapped)
            found.append({'key': name, 'matrix': where, 'matrix_from': source})

    return found, offset


def tail(path, limit=TAIL_BYTES):
    """The last part of a file as text, or '' when there is no file."""
    try:
        size = os.path.getsize(path)
        with open(path, 'r', errors='replace') as handle:
            if size > limit:
                handle.seek(size - limit)
                handle.readline()  # drop the half line the seek landed in
            return handle.read()
    except OSError:
        return ''


def from_log(path=LOG):
    """What LCDd's log says about keys.

    Returns (counts, matrix, lines_seen). The log carries no timestamps of its
    own - LCDproc writes plain lines - so this source can say how many and
    which, never when. The file's modification time is the closest honest
    answer to "when", and report() passes it on as exactly that.
    """
    counts = {}
    matrix = {}
    seen = 0

    for line in tail(path).splitlines():
        found = _KEYSTROKE.search(line)
        if found:
            counts[found.group(1)] = counts.get(found.group(1), 0) + 1
            seen += 1
            continue
        found = _MATRIX.search(line)
        if found:
            matrix[found.group(1)] = '%s,%s' % (found.group(2), found.group(3))

    return counts, matrix, seen


def log_level(path=config.LCDD_CONF):
    """The ReportLevel the generated configuration asks LCDd for.

    Read rather than assumed: the file on the disk is what LCDd was started
    with, and a user who edited it by hand deserves to be told the truth about
    what their log will and will not contain.
    """
    try:
        with open(path, 'r', errors='replace') as handle:
            for line in handle:
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue
                name, _, value = stripped.partition('=')
                if name.strip() == 'ReportLevel':
                    return int(value.strip())
    except (OSError, ValueError):
        return None
    return None


def configured_map(path=config.LCDD_CONF):
    """{key name: [matrix positions]} from the generated configuration.

    Read rather than remembered, for the same reason log_level() reads it: the
    file on the disk is the one LCDd was started with, and a map somebody edited
    by hand is still the map the driver is working from. A name appears with
    more than one position only when the map gave two keys the same name, which
    is worth showing as the two positions it is.
    """
    found = {}
    try:
        with open(path, 'r', errors='replace') as handle:
            for line in handle:
                match = _KEY_LINE.match(line.strip())
                if match:
                    found.setdefault(match.group(3), []).append(
                        '%s,%s' % (match.group(1), match.group(2)))
    except OSError:
        return {}
    return found


def place(name, seen=None, mapped=None):
    """Where on the keypad a key came from, and how that was arrived at.

    Returns (position, source). The driver's own line wins where the log has
    one, because it is a report of the wires; otherwise the map that was written
    for this panel is inverted, which is exact as long as no two positions were
    given the same name. '' for both when neither can say.
    """
    seen = seen or {}
    if seen.get(name):
        return seen[name], 'driver'

    mapped = configured_map() if mapped is None else mapped
    where = mapped.get(name) or []
    if where:
        return ' / '.join(where), config.LCDD_CONF
    return '', ''


def load_record(path=RECORD):
    try:
        with open(path, 'r') as handle:
            stored = json.load(handle)
    except (OSError, ValueError):
        return {'counts': {}, 'presses': [], 'started': None}

    stored.setdefault('counts', {})
    stored.setdefault('presses', [])
    stored.setdefault('started', None)
    return stored


def record_press(key, path=RECORD, now=None):
    """Write down one key press that reached the screen client.

    Called from the client, and only when a key actually arrives. Presses are
    rare events on a rack appliance, so one small write each is affordable in a
    way that a periodic write would not be.
    """
    now = int(now or time.time())
    stored = load_record(path)
    stored['counts'][key] = stored['counts'].get(key, 0) + 1
    stored['presses'] = (stored['presses'] + [{'key': key, 'at': now}])[-KEEP_PRESSES:]
    if not stored.get('started'):
        stored['started'] = now

    config.write_atomic(path, json.dumps(stored, separators=(',', ':')))
    return stored


def forget(path=RECORD):
    """Throw the client's record away, so a key test starts from nothing."""
    try:
        os.unlink(path)
    except OSError:
        pass


def report(options=None, log=LOG, record=RECORD):
    """Everything known about this panel's keys, for the settings page.

    Deliberately not a verdict. It says what each source saw and lets the page
    put it in front of the owner: on hardware nobody has confirmed, "the driver
    reported Enter eight times and nothing else" is far more useful than a
    green tick or a red cross.
    """
    options = options if options is not None else config.settings()

    log_counts, matrix, log_seen = from_log(log)
    stored = load_record(record)
    level = log_level()

    try:
        log_mtime = int(os.path.getmtime(log))
    except OSError:
        log_mtime = None

    keys = {}
    for name, count in log_counts.items():
        keys.setdefault(name, {'name': name, 'log': 0, 'client': 0, 'matrix': ''})['log'] = count
    for name, count in (stored.get('counts') or {}).items():
        keys.setdefault(name, {'name': name, 'log': 0, 'client': 0, 'matrix': ''})['client'] = count
    for name in matrix:
        keys.setdefault(name, {'name': name, 'log': 0, 'client': 0, 'matrix': ''})

    # Where each of them is on the keypad. The driver's own line where the log
    # holds one, the written map read backwards where it does not - and the
    # answer says which, because "the driver reported 4,1" and "the map we wrote
    # says 4,1" are not the same statement and only the first is a measurement.
    mapped = configured_map()
    for entry in keys.values():
        entry['matrix'], entry['matrix_from'] = place(entry['name'], matrix, mapped)

    presses = list(stored.get('presses') or [])
    total = log_seen + sum((stored.get('counts') or {}).values())

    answer = {
        'status': 'ok',
        'keypad': bool(options.get('keypad')),
        'any': bool(keys),
        'total': total,
        'keys': [keys[name] for name in sorted(keys)],
        'recent': presses[-10:],
        'log': {
            'path': log,
            'exists': os.path.exists(log),
            'lines_with_keys': log_seen,
            'report_level': level,
            'reports_keys': level is not None and level >= config.REPORT_LEVEL_KEYS,
            'newest': log_mtime,
        },
        'client': {
            'path': record,
            'since': stored.get('started'),
            'presses': sum((stored.get('counts') or {}).values()),
        },
    }

    if not options.get('keypad'):
        answer['note'] = ('The keypad is switched off in the settings, so nothing is '
                          'polling the keys and nothing will be reported.')
    elif not keys:
        answer['note'] = ('No key has reported yet. The keys are polled rather than '
                          'volunteered, so press one and look again - and if nothing ever '
                          'arrives, this panel\'s driver may simply not be able to read '
                          'them, which is a limit of the hardware and not a fault.')
    elif answer['log']['report_level'] is not None and not answer['log']['reports_keys']:
        answer['note'] = ('LCDd is writing at report level %d, and it only names a key in '
                          'its log at level %d or higher. What is shown here came from the '
                          'screen client, which is the stronger evidence anyway.'
                          % (answer['log']['report_level'], config.REPORT_LEVEL_KEYS))

    return answer
