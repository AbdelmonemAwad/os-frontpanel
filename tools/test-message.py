#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause
# Copyright (c) 2026 Abdelmonem Awad <eg2@live.com>
"""The message screen's two lines: what config.py reads out of config.xml - the defaults, a line
emptied, and a message saved as one line before there were two - what the panel is sent, cut at its
width one line to a row, and what the preview is handed, uncut, so the page can show the cut. The
defaults are held to the same text in the three places that write them down: the model, the model's
PHP and config.py. Nothing here touches a firewall: config.xml is a string, and no screen but the
message is drawn.

The model's migration (Migrations/M1_2_0.php) needs the OPNsense framework and does not run here;
config.py decides the same three cases as it does, and that is what is checked.

    python3 tools/test-message.py"""
import importlib.util
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, 'src', 'opnsense', 'scripts', 'frontpanel')
MODEL = os.path.join(ROOT, 'src', 'opnsense', 'mvc', 'app', 'models', 'OPNsense', 'FrontPanel')
failures = 0


def check(name, got, want):
    global failures
    ok = got == want
    failures += 0 if ok else 1
    print('%s %s%s' % ('ok  ' if ok else 'FAIL', name, '' if ok else ' - got %r, want %r' % (got, want)))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config = load('config')
screens = load('screens')

FIRST, SECOND = '@NPUforge', 'https://npuforge.org/'


def saved(general):
    """config.xml with these elements under the plugin's general, as settings() reads it."""
    return ET.fromstring('<opnsense><OPNsense><FrontPanel><general>%s</general></FrontPanel>'
                         '</OPNsense></opnsense>' % general)


def lines(general):
    values = config.settings(saved(general))
    return [values['message'], values['message2']]


# The defaults, written down three times.
model = ET.parse(os.path.join(MODEL, 'FrontPanel.xml')).getroot()
check('the model ships both lines with their defaults',
      [model.findtext('items/general/message/Default'), model.findtext('items/general/message2/Default')],
      [FIRST, SECOND])
check('the model is version 1.2.0, the migration\'s', model.findtext('version'), '1.2.0')
check('the migration is there', os.path.isfile(os.path.join(MODEL, 'Migrations', 'M1_2_0.php')), True)
php = open(os.path.join(MODEL, 'FrontPanel.php'), encoding='utf-8').read()
check('FrontPanel.php knows the same defaults',
      re.search(r"MESSAGE_DEFAULTS = \['message' => '([^']*)', 'message2' => '([^']*)'\]", php).groups(),
      (FIRST, SECOND))
check('config.py knows the same defaults', [config.DEFAULTS['message'], config.DEFAULTS['message2']],
      [FIRST, SECOND])

# What config.py reads.
check('no settings at all: both defaults', lines(''), [FIRST, SECOND])
check('settings saved before 1.2.0 with no message element: both defaults',
      lines('<enabled>1</enabled>'), [FIRST, SECOND])
check('a message saved before 1.2.0 stays, as the first line, and the second is empty',
      lines('<message>Ask Abdelmonem before unplugging</message>'),
      ['Ask Abdelmonem before unplugging', ''])
check('a message saved empty before 1.2.0 - as every earlier version shipped it: both defaults',
      lines('<message/>'), [FIRST, SECOND])
check('two lines saved: both, as written',
      lines('<message> Do not power off </message><message2>ask Abdelmonem</message2>'),
      ['Do not power off', 'ask Abdelmonem'])
check('the second line emptied stays empty', lines('<message>One</message><message2/>'), ['One', ''])
check('the first line emptied stays empty', lines('<message/><message2>Two</message2>'), ['', 'Two'])
check('both emptied stay empty', lines('<message/><message2/>'), ['', ''])

# What the panel is sent: one line to a row, each cut at the width and never carried over.
check('16x2, the defaults: the address is cut at 16',
      screens.render('message', 16, 2, {'message': FIRST, 'message2': SECOND}),
      ['@NPUforge', 'https://npuforge'])
check('20x2, the defaults: the address is cut at 20',
      screens.render('message', 20, 2, {'message': FIRST, 'message2': SECOND}),
      ['@NPUforge', 'https://npuforge.org'])
check('a long first line is cut, not carried onto the second row',
      screens.render('message', 16, 2, {'message': 'Do not power this off', 'message2': ''}),
      ['Do not power thi', ''])
check('only the second line: the first row is blank',
      screens.render('message', 16, 2, {'message': '', 'message2': 'ask Abdelmonem'}),
      ['', 'ask Abdelmonem'])
check('both lines empty: the screen has nothing to say',
      screens.render('message', 16, 2, {'message': '', 'message2': ''}), None)
check('text that is not plain Latin is folded, as it was',
      screens.render('message', 16, 2, {'message': '\u00dcbersicht', 'message2': '\u0645\u0631\u062d\u0628\u0627'}),
      ['Ubersicht', '?????'])


def preview(options, width=16):
    entry = [item for item in screens.catalogue(width, 2, options, only=['message'])
             if item['key'] == 'message'][0]
    return {name: entry.get(name) for name in ('lines', 'available', 'source', 'reason')}


# What the preview is handed: folded, never cut, so the page draws the cut past the edge.
check('the preview of the defaults at 16 columns carries the whole address',
      preview({'message': FIRST, 'message2': SECOND}),
      {'lines': [FIRST, SECOND], 'available': True, 'source': None, 'reason': None})
check('the preview says what was typed beside what is drawn',
      preview({'message': '\u00dcbersicht', 'message2': 'plain'}),
      {'lines': ['Ubersicht', 'plain'], 'available': True, 'source': '\u00dcbersicht | plain', 'reason': None})
check('the preview of an empty message says why it is skipped',
      preview({'message': '', 'message2': ''}),
      {'lines': [], 'available': False, 'source': None, 'reason': 'both lines of the message are empty'})

print('%d failed' % failures if failures else 'all passed')
sys.exit(1 if failures else 0)
