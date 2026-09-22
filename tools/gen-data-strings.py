#!/usr/local/bin/python3
"""Regenerate the page's map of translatable DATA strings.

The page translates through lang._() like every other part of OPNsense, and lang._()
resolves at template-compile time against a literal. That is fine for the page's own
sentences and impossible for text that lives in a data file, so index.volt carries a map
from the English in panels.json to the same English passed through lang._(). Every entry
has to be listed, which means a note added to panels.json comes out in English on an
otherwise Arabic page - and nothing says so.

This closes that hole: the map is built from the data file rather than remembered, and
any string it finds that the catalogue does not know is reported by name. Run it after
touching panels.json; the installer runs it too.

    tools/gen-data-strings.py [--check]

--check changes nothing and exits 1 if the map or the catalogue is out of date, which is
what a build should run.

This is os-linkhealth's generator with its field list and its file list changed, and one
repair. Its replace_block backs up over ONE comment before the map; when the comment is
reworded it replaces that one and leaves the previous copy behind. os-linkhealth's own
index.volt carries the proof - the same six-line comment appears twice, at lines 337 and
343, measured 2026-09-22. The loop below walks back over every comment that names the map
instead of only the last one, which is idempotent.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANELS = os.path.join(HERE, 'src', 'opnsense', 'scripts', 'frontpanel', 'panels.json')
CATALOGUE = os.path.join(HERE, 'src', 'opnsense', 'scripts', 'frontpanel', 'i18n', 'ui')
VIEW = os.path.join(HERE, 'src', 'opnsense', 'mvc', 'app', 'views',
                    'OPNsense', 'FrontPanel', 'index.volt')

NAME = 'fp_data_text'
BEGIN = '        const %s = {' % NAME
END = '        };'

# The fields in panels.json that end up in front of a reader: the name of the appliance
# the entry is for, the sentence saying how far the proposal has been proven, the sentence
# that tells somebody what to try when it has not, and the notes explaining the options.
#
# A field not listed here is either an identifier the page never prints as prose (driver,
# match, keymap, options, speed) or the file's own marginalia (comment), which is written
# for whoever opens panels.json and never reaches a browser at all.
#
# 'notes' is harvested although index.volt does not render it yet: frontpanel.py hands the
# whole matched entry to the page under 'panel', notes included, so the day the page prints
# them they are already in the catalogue rather than five English paragraphs on an Arabic
# page. That is the bug this file exists to prevent, and it costs five msgids to prevent it
# in advance instead of after somebody has seen it.
TEXT_FIELDS = ('display', 'hint', 'confirmed', 'notes')


def harvest():
    """Every reader-facing string in panels.json, in a stable order."""
    found = []
    seen = set()

    def keep(value):
        value = value.strip()
        if value and value not in seen:
            seen.add(value)
            found.append(value)

    def walk(node):
        if isinstance(node, dict):
            for field in TEXT_FIELDS:
                value = node.get(field)
                if isinstance(value, str):
                    keep(value)
                elif isinstance(value, list):
                    # notes is a list of sentences; each one is its own msgid, because a
                    # paragraph joined here would change msgid the moment somebody adds a
                    # sentence to it and silently lose the Arabic for the other four
                    for item in value:
                        if isinstance(item, str):
                            keep(item)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    with open(PANELS, encoding='utf-8') as handle:
        walk(json.load(handle))
    return found


def as_js(value):
    """A JS single-quoted literal, and the Volt call that translates it.

    Volt ends a single-quoted string at the first unescaped quote, so an apostrophe has to
    arrive as backslash-apostrophe in BOTH places - and as exactly one backslash. Two is
    what broke the sibling plugin's page once already: Volt read the first as an escaped
    backslash and the string ended in the middle of a sentence. panels.json has apostrophes
    in it today - LCDproc's, the driver's own - so this is not a precaution.
    """
    return value.replace(chr(92), chr(92) * 2).replace(chr(39), chr(92) + chr(39))


def build_block(strings):
    lines = [
        '        /* Translatable text that lives in panels.json, not in this page: the name of',
        '           each known appliance, the sentence saying how far its panel has actually been',
        '           proven, and the notes beside it. lang._() resolves against a literal at compile',
        '           time, so each one is listed as its own key - and %s is GENERATED, by' % NAME,
        '           tools/gen-data-strings.py, because a note added to panels.json and forgotten',
        '           here comes out in English on an Arabic page with nothing to say so. */',
        BEGIN,
    ]
    for value in strings:
        literal = as_js(value)
        entry = "            '%s': \"{{ lang._('%s') }}\"," % (literal, literal)
        if len(entry) > 100:
            lines.append("            '%s':" % literal)
            lines.append("                \"{{ lang._('%s') }}\"," % literal)
        else:
            lines.append(entry)
    if len(lines) > 7:
        lines[-1] = lines[-1].rstrip(',')
    lines.append(END)
    return '\n'.join(lines)


def replace_block(text, block):
    start = text.index(BEGIN)
    # Back up over the comment that introduces the map - over every one of them. Replacing
    # only the last leaves the earlier copy sitting above it, which is how the sibling
    # plugin's page ended up with the same paragraph twice.
    while True:
        head = text.rfind('\n        /*', 0, start)
        if head == -1:
            break
        chunk = text[head + 1:start]
        mine = NAME in chunk or 'gen-data-strings.py' in chunk
        if not mine or not chunk.rstrip().endswith('*/'):
            break
        start = head + 1
    finish = text.index('\n' + END, text.index(BEGIN)) + len('\n' + END)
    return text[:start] + block + text[finish:]


def main():
    check = '--check' in sys.argv
    strings = harvest()
    block = build_block(strings)

    with open(VIEW, encoding='utf-8') as handle:
        text = handle.read()
    if BEGIN not in text:
        # Not something to paper over by inserting a block at a guessed anchor: where the
        # map sits in the page is the page's business, and a generator that decides it
        # would be rewriting a file it does not understand.
        print('index.volt has no "%s" map to regenerate. Add the block and the fp_data()'
              % NAME)
        print('helper beside the other translation tables, then run this again.')
        return 1
    updated = replace_block(text, block)

    with open(os.path.join(CATALOGUE, 'source.json'), encoding='utf-8') as handle:
        source = json.load(handle)
    with open(os.path.join(CATALOGUE, 'ar_SA.json'), encoding='utf-8') as handle:
        arabic = json.load(handle)

    missing = [s for s in strings if s not in source]
    untranslated = [s for s in strings if s not in arabic]

    if check:
        problems = 0
        if updated != text:
            print('the data-string map in index.volt is out of date')
            problems += 1
        for value in missing:
            print('not in source.json: %s' % value[:80])
            problems += 1
        for value in untranslated:
            print('no Arabic: %s' % value[:80])
            problems += 1
        if problems == 0:
            print('data strings: %d, all mapped and translated' % len(strings))
        return 1 if problems else 0

    if updated != text:
        with open(VIEW, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(updated)
        print('map rewritten: %d data strings' % len(strings))
    else:
        print('map already current: %d data strings' % len(strings))

    for value in missing:
        source.append(value)
    if missing:
        with open(os.path.join(CATALOGUE, 'source.json'), 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(source, handle, ensure_ascii=False, indent=1)
            handle.write('\n')
        print('added to source.json: %d' % len(missing))
    for value in untranslated:
        print('NEEDS ARABIC: %s' % value[:90])
    return 0


if __name__ == '__main__':
    sys.exit(main())
