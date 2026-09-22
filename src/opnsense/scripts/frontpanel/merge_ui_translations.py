#!/usr/local/bin/python3

"""
Copyright (C) 2026 Abdelmonem Awad <eg2@live.com>
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

Add the Front Panel GUI strings (i18n/ui/<locale>.json) to the OPNsense gettext
catalog of every installed GUI language. Strings the catalog already translates are left
alone, so running it again is harmless. Prints the number of strings added; a catalog that
cannot be read is named on stderr and the remaining languages are still done.

Three things run it, and the third is the one that keeps the page Arabic:

    install/install.sh                        a repository unpacked by hand
    pkg/post-install.sh                       the package, on install and on upgrade
    src/etc/rc.syshook.d/start/63-frontpanel  every boot

The boot hook is not belt and braces. A core update replaces
/usr/local/share/locale/*/LC_MESSAGES/OPNsense.mo outright, and everything this script
ever added to it goes with it; without a hook the page would quietly return to English
after an update and stay there until somebody reinstalled the package. The number 63 is
not free either: 59-opnsense-arabic is what puts the ar_SA catalog itself back when an
update removed it, and merging into a catalog that is not there yet adds nothing. Anything
above 59 is correct; 60 and 62 are taken by os-netreport and os-linkhealth.

This is os-linkhealth's merge with three names changed - the directory it reads, the
ledger it keeps and the temporary file it writes. It is deliberately a copy rather than a
shared library: the two plugins install independently of each other, and a plugin that
could not translate itself without its sibling present would be a plugin that stops
speaking Arabic the day somebody removes the other one.
"""

import glob
import json
import os
import struct
import sys

LOCALE_DIR = '/usr/local/share/locale'
UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'i18n', 'ui')


def read_mo(path):
    """msgid bytes -> msgstr bytes (plural and context entries kept as raw bytes)"""
    data = open(path, 'rb').read()
    magic = struct.unpack('<I', data[:4])[0]
    endian = '<' if magic == 0x950412de else '>'
    _, count, orig_off, trans_off = struct.unpack(endian + '4I', data[4:20])
    entries = {}
    for i in range(count):
        olen, opos = struct.unpack(endian + '2I', data[orig_off + 8 * i:orig_off + 8 * i + 8])
        tlen, tpos = struct.unpack(endian + '2I', data[trans_off + 8 * i:trans_off + 8 * i + 8])
        entries[data[opos:opos + olen]] = data[tpos:tpos + tlen]
    return entries


def write_mo(path, entries):
    """standard little-endian .mo without a hash table (gettext then uses binary search)"""
    keys = sorted(entries)
    count = len(keys)
    orig_off = 28
    trans_off = orig_off + 8 * count
    data_off = trans_off + 8 * count
    ids = strs = b''
    orig_tab, trans_tab = [], []
    for k in keys:
        orig_tab.append((len(k), len(ids)))
        ids += k + b'\0'
    for k in keys:
        trans_tab.append((len(entries[k]), len(strs)))
        strs += entries[k] + b'\0'
    out = struct.pack('<7I', 0x950412de, 0, count, orig_off, trans_off, 0, data_off)
    for length, pos in orig_tab:
        out += struct.pack('<2I', length, data_off + pos)
    for length, pos in trans_tab:
        out += struct.pack('<2I', length, data_off + len(ids) + pos)
    out += ids + strs
    # A temporary name of our own, and it buys exactly one thing. os-linkhealth and
    # os-netreport ship the same merge and run it from their own boot hooks, and all three
    # can be installed on this machine, so two of them writing one temp path is not a
    # hypothetical: the reader would find half of one plugin's catalogue and half of
    # another's in a single file. A private name makes every file that appears at `path`
    # a complete, parseable catalogue.
    #
    # What it does not buy is the other half of that problem. Each run reads the whole
    # catalogue, adds to it and writes the whole thing back, with no lock: if two of these
    # ever overlap, the second one's copy wins and the first one's strings are simply not
    # in it. Nothing here prevents that. The boot hooks are numbered and rc.syshook.d runs
    # them one after another, which is the only reason the common case is safe; a lock
    # would have to be added to all three merges at once to be worth anything, since a lock
    # one party takes and the others ignore is not a lock.
    tmp = path + '.frontpanel.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(out)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


OWNED = '/var/db/frontpanel/i18n-owned.json'


def owned():
    """The msgids this plugin has written into the catalogues itself.

    A catalogue holds core's translations and ours in one file, and the rule
    "never touch a string that is already translated" is what keeps this from
    rewording the whole GUI. The page, its API and its XML between them ask the
    catalogue for 125 msgids - 79 lang._() calls in index.volt, 76 of them
    distinct; 5 gettext() in the controller and the model; 50 label, help, hint,
    name and VisibleName nodes in the form, model, menu and ACL XML - and 16 of
    those 125 are already core's own words:

        Close, Connection type, Diagnostics, Driver, Enabled, Key, Message,
        Preview, Refresh, Serial port, Settings, Size, Temperature, running,
        stopped, unknown

    Core's Arabic for all 16 must win, and one more - "Front panel" - is in the
    catalogue because os-linkhealth put it there, and is left alone for the same
    reason. That leaves 108 this plugin adds. Measured against the installed
    ar_SA catalogue (14745 entries) on 2026-09-22 by harvesting the msgids from
    the templates and looking each one up in the .mo.

    But that rule also froze OUR OWN strings: correcting a word here would
    never reach the catalogue, because the catalogue already had the old one.
    So the script remembers what it wrote. Anything in this list is ours to
    correct; anything else is left exactly as it was found - --force was run
    against a copy of that catalogue with a word of ours put against core's
    "Settings", and "Settings" still read back core's Arabic afterwards.
    """
    try:
        with open(OWNED, 'r') as handle:
            return {locale: set(ids) for locale, ids in json.load(handle).items()}
    except (OSError, ValueError):
        return {}


def remember(state):
    try:
        os.makedirs(os.path.dirname(OWNED), mode=0o750, exist_ok=True)
        with open(OWNED, 'w') as handle:
            json.dump({locale: sorted(ids) for locale, ids in state.items()}, handle)
        os.chmod(OWNED, 0o640)
    except OSError:
        pass          # the merge itself succeeded; the bookkeeping is a nicety


def main():
    force = '--force' in sys.argv
    state = owned()
    added_total = 0
    for src in sorted(glob.glob(os.path.join(UI_DIR, '*_*.json'))):
        locale = os.path.basename(src)[:-5]
        mo = os.path.join(LOCALE_DIR, locale, 'LC_MESSAGES', 'OPNsense.mo')
        if not os.path.exists(mo):
            continue
        try:
            strings = json.load(open(src, encoding='utf-8'))
            entries = read_mo(mo)
        except Exception as exc:
            print(f'{locale}: skipped ({exc})', file=sys.stderr)
            continue
        mine = state.setdefault(locale, set())
        added = 0
        for msgid, msgstr in strings.items():
            if not msgstr:
                continue
            key = msgid.encode('utf-8')
            current = entries.get(key)
            if not current:
                entries[key] = msgstr.encode('utf-8')
                mine.add(msgid)
                added += 1
            elif force and msgid in mine and current != msgstr.encode('utf-8'):
                entries[key] = msgstr.encode('utf-8')
                added += 1
        if added:
            write_mo(mo, entries)
            read_mo(mo)          # sanity check: the result must parse
        added_total += added
    remember(state)
    print(added_total)


if __name__ == '__main__':
    main()
