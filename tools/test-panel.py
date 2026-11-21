#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause
# Copyright (c) 2026 Abdelmonem Awad <eg2@live.com>
"""What an XGS 3100's owner asked for (os-xgs-npu issues 901 and 990), as far as it can be checked
without a panel: the throughput screen once for each chosen interface, and the migration that turns
the one kernel name saved before 1.3.0 into an interface; the keys stopping the rotation on the
screen being shown and giving it back after a stretch with no key; the appliance table's entry for
the XGS 3100 alone; the heartbeat never applied on a panel the plugin draws itself; and the list of
saved settings that differ from this appliance's entry.

Nothing here touches a firewall. config.xml is a string, the interfaces are a table handed in, no
counter is read, and the screen client is driven with a stand-in for the panel that only records
what it is sent. The migration runs under PHP against two stand-in classes for the framework's,
where PHP is installed; without it that part says so and is skipped.

    python3 tools/test-panel.py"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, 'src', 'opnsense', 'scripts', 'frontpanel')
MIGRATION = os.path.join(ROOT, 'src', 'opnsense', 'mvc', 'app', 'models', 'OPNsense', 'FrontPanel',
                         'Migrations', 'M1_3_0.php')
failures = 0


def check(name, got, want):
    global failures
    ok = got == want
    failures += 0 if ok else 1
    print('%s %s%s' % ('ok  ' if ok else 'FAIL', name, '' if ok else ' - got %r, want %r' % (got, want)))


sys.path.insert(0, SCRIPTS)


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


config = load('config')
screens = load('screens')

TABLE = {
    'wan': {'if': 'igb0', 'descr': 'Fibre'},
    'lan': {'if': 'igb1', 'descr': ''},
    'opt1': {'if': 'igb2', 'descr': 'Guests'},
}
screens.interfaces = lambda: TABLE
screens.throughput_rate = lambda device: (8000.0, 16000.0)


def targets(**options):
    return [(key, device) for key, device, _ in screens.throughput_targets(options, TABLE)]


# --- one throughput screen per chosen interface, in the order chosen ---------------------------

check('nothing chosen is the WAN', targets(throughput_if=''), [('throughput', 'igb0')])
check('one interface', targets(throughput_if='opt1'), [('throughput', 'igb2')])
check('several, in the order chosen', targets(throughput_if='opt1,wan,lan'),
      [('throughput', 'igb2'), ('throughput_wan', 'igb0'), ('throughput_lan', 'igb1')])
check('an interface named twice is one screen', targets(throughput_if='lan,lan'), [('throughput', 'igb1')])
check('an interface since removed is passed over', targets(throughput_if='opt9,lan'), [('throughput', 'igb1')])
check('and alone, the WAN takes its place', targets(throughput_if='opt9'), [('throughput', 'igb0')])

options = {'screens': 'identity,throughput,system', 'throughput_if': 'lan,opt1'}
check('the rotation carries one screen per interface', screens.chosen(options),
      ['identity', 'throughput', 'throughput_opt1', 'system'])
check('the throughput screen kept out of the rotation takes all of them out',
      screens.chosen({'screens': 'identity,system', 'throughput_if': 'lan,opt1'}), ['identity', 'system'])
check('each named by its description', screens.render('throughput_opt1', 16, 2, options),
      ['Guests', 'Rx8.0k Tx16k'])
check('an interface with no description by its name', screens.render('throughput', 16, 2, options),
      ['LAN', 'Rx8.0k Tx16k'])
check('a key no interface stands behind draws nothing', screens.render('throughput_wan', 16, 2, options), None)
check("the menu's name for a throughput screen", screens.title('throughput_opt1', options), 'Throughput Guests')
check("the menu's name for any other screen", screens.title('system', options), 'System')

listed = screens.catalogue(16, 2, {'screens': 'throughput,system', 'throughput_if': 'opt1,wan'})
check('the preview, in the rotation order',
      [(entry['key'], entry['kind'], entry.get('name')) for entry in listed][:3],
      [('throughput', 'throughput', 'Guests'), ('throughput_wan', 'throughput', 'Fibre'), ('system', 'system', None)])

# --- a value saved before 1.3.0, before and after the migration ---------------------------------

check('before the migration: a kernel name an interface owns',
      targets(throughput_if='igb2'), [('throughput', 'igb2')])
check('before the migration: a kernel name nobody owns is still measured',
      targets(throughput_if='ix0'), [('throughput', 'ix0')])
check('after the migration: the name kept aside is measured while nothing is chosen',
      targets(throughput_if='', throughput_dev='ix0'), [('throughput', 'ix0')])
check('after the migration: a choice in the list replaces it',
      targets(throughput_if='lan', throughput_dev='ix0'), [('throughput', 'igb1')])

saved = config.settings(config.ET.fromstring(
    '<opnsense><OPNsense><FrontPanel><general><throughput_if>wan,opt1</throughput_if>'
    '<throughput_dev>ix0</throughput_dev></general></FrontPanel></OPNsense></opnsense>'))
check('config.py reads both fields', (saved['throughput_if'], saved['throughput_dev']), ('wan,opt1', 'ix0'))

# Config::object() hands the migration config.xml as SimpleXML; this stand-in answers the four
# things the migration asks of it (a child by name, isset, children() and the text), so the test
# needs no PHP extension beyond json.
STUBS = r'''<?php
namespace OPNsense\Base { class BaseModelMigration {} }
namespace OPNsense\Core {
    class Node {
        private $text = '';
        private $kids = [];
        public function __construct($data) {
            if (is_array($data)) {
                foreach ($data as $name => $value) { $this->kids[$name] = new Node($value); }
            } else {
                $this->text = (string)$data;
            }
        }
        public function __get($name) { return $this->kids[$name] ?? null; }
        public function __isset($name) { return isset($this->kids[$name]); }
        public function children() { return $this->kids; }
        public function __toString() { return $this->text; }
    }
    class Config {
        public static $saved;
        public static function getInstance() { return new Config(); }
        public function object() { return self::$saved; }
    }
}
namespace {
    require $argv[1];
    \OPNsense\Core\Config::$saved = new \OPNsense\Core\Node(json_decode($argv[2], true));
    $model = new stdClass();
    $model->general = new stdClass();
    $model->general->throughput_if = $argv[3];
    $model->general->throughput_dev = '';
    (new \OPNsense\FrontPanel\Migrations\M1_3_0())->run($model);
    echo json_encode([$model->general->throughput_if, $model->general->throughput_dev]);
}
'''

INTERFACES = {'wan': {'if': 'igb0'}, 'lan': {'if': 'igb1'}, 'opt1': {'if': 'igb2'}}


def migrated(saved_value):
    general = {} if saved_value is None else {'throughput_if': saved_value}
    saved = {'interfaces': INTERFACES, 'OPNsense': {'FrontPanel': {'general': general}}}
    folder = tempfile.mkdtemp()
    try:
        script = os.path.join(folder, 'run.php')
        with open(script, 'w') as handle:
            handle.write(STUBS)
        out = subprocess.run(['php', script, MIGRATION, json.dumps(saved), saved_value or ''],
                             capture_output=True, text=True)
        return out.stdout.strip() or out.stderr.strip()
    finally:
        shutil.rmtree(folder)


if shutil.which('php'):
    check('migration: nothing saved', migrated(None), '["",""]')
    check('migration: saved empty, still the WAN', migrated(''), '["",""]')
    check('migration: the device behind the WAN becomes the WAN', migrated('igb0'), '["wan",""]')
    check('migration: the device behind opt1 becomes opt1', migrated('igb2'), '["opt1",""]')
    check('migration: a device no interface owns is kept aside', migrated('ix0'), '["","ix0"]')
    check('migration: already an interface name', migrated('opt1'), '["opt1",""]')
else:
    print('skip the migration: no php here')

# --- the XGS 3100's entry -------------------------------------------------------------------------

table = config.load_panels()
# The entries are found by what they match, and the maker by what they ask for, so that this file
# names no appliance maker of its own.
PANELS = table['panels']
BOARD = next(k for k, v in PANELS.items() if v.get('match', {}).get('serial') == 'AMDA0202-')
XGS3300 = next(k for k, v in PANELS.items() if '3300r1' in v.get('match', {}).get('version', ''))
XG330 = next(k for k, v in PANELS.items() if v.get('match', {}).get('product') == '^XG$')
MAKER = PANELS[XGS3300]['match']['maker'].strip('^$')


def matched(**fields):
    return config.match_panel(table, fields)[0]


key, entry = config.match_panel(table, {'maker': MAKER, 'product': 'XGS', 'version': '',
                                        'serial': 'AMDA0202-0003 0123456789'})
check('an XGS 3100 matches its own entry', key, 'xgs-3100')
check('which is confirmed', bool(entry.get('confirmed')), True)
check('at 9600, 20x2, drawn by the plugin',
      (entry['options'].get('Speed'), entry['options'].get('Size'), entry.get('direct')), ('9600', '20x2', True))
check('the text starts at offset 24', entry.get('offset'), 24)
check('and its comment says where that comes from', 'issue 901' in ' '.join(entry.get('comment') or []), True)
check('an XGS 2100 still has the board entry',
      matched(maker=MAKER, product='XGS', version='', serial='AMDA0202-0001 0123'), BOARD)
check('which is still unconfirmed', PANELS[BOARD]['confirmed'], '')
check('an XGS 3300 still has its own', matched(maker=MAKER, product='XGS', version='17', serial=''), XGS3300)

# --- the heartbeat, and what differs from the entry ----------------------------------------------

direct = dict(config.DEFAULTS, driver='hd44780', connection='ezio', device='/dev/cuau1', size='20x2',
              heartbeat=True)
check('no heartbeat on a panel the plugin draws', config.heartbeat(direct, entry), False)
check('nor in the configuration written for it', 'Heartbeat=off' in config.render(direct, entry)[0], True)
general = PANELS[XG330]
lcdd = dict(direct, size='16x2')
check('the heartbeat where LCDd draws the panel', config.heartbeat(lcdd, general), True)

check('nothing differs when the settings are the entry', config.differences(direct, entry), [])
check('what differs, and the entry\'s value',
      config.differences(dict(direct, size='16x2', keypad=False), entry),
      [{'field': 'size', 'saved': '16x2', 'entry': '20x2'},
       {'field': 'keypad', 'saved': 'off', 'entry': 'on'}])
check('an entry that proposes nothing differs from nothing',
      config.differences(direct, PANELS['generic']), [])

# --- the keys stop the rotation ------------------------------------------------------------------

try:
    frontpanel = load('frontpanel')
except ImportError as missing:
    # bridge.py needs termios, which is POSIX: the checks run on Linux.
    frontpanel = None
    print('skip the keys: %s' % missing)

if frontpanel is not None:
    class Glass(object):
        def __init__(self):
            self.sent = []

        def send(self, line):
            self.sent.append(line)

    frontpanel.keypad.record_press = lambda name: None
    frontpanel.screens.render = lambda key, width, height, options: ['x', 'y']

    def client():
        one = frontpanel.Client.__new__(frontpanel.Client)
        one.options = {'screens': 'identity,wan,system', 'keys': []}
        one.actions = frontpanel.keypad.actions_for(one.options)
        one.panel = Glass()
        one.direct = False
        one.width, one.height = 20, 2
        one.added = ['identity', 'wan', 'system']
        one.shown = {}
        one.visible = 'wan'
        one.pinned = ''
        one.pinned_at = 0.0
        one.held = False
        one.menu = None
        one.aligning = False
        return one

    panel = client()
    panel.key('Down')
    check('the first press stops the rotation on the screen shown', panel.pinned, 'wan')
    panel.key('Down')
    check('the next press steps as before', panel.pinned, 'system')
    panel.key('Up')
    check('and back', panel.pinned, 'wan')
    pressed = panel.pinned_at
    panel.resume(pressed + frontpanel.PINNED_SECONDS - 1)
    check('held while a key was pressed lately', panel.pinned, 'wan')
    panel.resume(pressed + frontpanel.PINNED_SECONDS)
    check('given back after a stretch with no key', panel.pinned, '')

    panel = client()
    panel.key('Escape')
    check('Escape while rotating leaves the rotation running', panel.pinned, '')
    panel.key('Down')
    panel.key('Escape')
    check('Escape gives the screens back, as before', panel.pinned, '')

    panel = client()
    panel.options['keys'] = [{'key': 'Left', 'action': 'none'}]
    panel.actions = frontpanel.keypad.actions_for(panel.options)
    panel.key('Left')
    check('a key with nothing to do still stops the rotation', panel.pinned, 'wan')

    panel = client()
    panel.key('Enter')
    check('Enter still opens the menu', panel.menu is not None, True)

    panel = client()
    panel.options['keys'] = [{'key': 'Left', 'action': 'pause'}]
    panel.actions = frontpanel.keypad.actions_for(panel.options)
    panel.key('Left')
    panel.resume(panel.pinned_at + frontpanel.PINNED_SECONDS * 10)
    check('the hold key still holds until it is pressed again', panel.pinned, 'wan')

print('%d failed' % failures if failures else 'all passed')
sys.exit(1 if failures else 0)
