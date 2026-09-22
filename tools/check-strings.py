#!/usr/local/bin/python3
"""Every string the GUI asks the catalogue for, against every string the catalogue holds.

A msgid that reaches gettext without being in source.json is shown in English on an
otherwise Arabic page, and nothing in the build would have said so.

Four places ask, and all four are checked, because all four go through the same catalogue:

  page    index.volt, through lang._() - 79 calls, 76 distinct
  form    controllers/.../forms/general.xml: <label>, <help> and <hint>. ControllerBase's
          parseFormNode passes all three through gettext() (V: ControllerBase.php:225-234
          on OPNsense 26.7.4_1, read 2026-09-22)
  model   models/.../FrontPanel.xml: <ValidationMessage>, which BaseField::getValidationMessage
          passes through gettext() (V: BaseField.php:911), and <OptionValues> text, which
          OptionField passes through gettext() as well (V: OptionField.php:48)
  data    panels.json, through the generated map in index.volt - counted as page strings
          here, because that is literally what they are once the map is written

os-linkhealth's own check reads the .volt files and nothing else, which is why the 14
ValidationMessages in its model are missing from its catalogue to this day (measured
2026-09-22: 0 of 14 present). That is the hole this version does not have.

Exit status matters. The job that runs this used to pass because the file did not exist,
which is worse than failing: a green check that checks nothing. A msgid the page asks for
and the catalogue does not hold, or holds without Arabic, fails the build.
"""
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BS = chr(92)
Q = chr(39)

# lang._('...') with backslash escapes inside, the way Volt writes them
PATTERN = re.compile("lang" + BS + "._" + BS + "(" + BS + "s*" + Q
                     + "((?:[^" + Q + BS + BS + "]|" + BS + BS + ".)*)" + Q
                     + BS + "s*" + BS + ")")
# Every call, however it is quoted, so that one written with double quotes is reported
# rather than quietly dropped by the pattern above. A quote is required after the bracket
# because "lang._()" also appears in prose - the comment above the generated data map says
# what lang._() does - and a comment is not a call.
ANY_CALL = re.compile("lang" + BS + "._" + BS + "(" + BS + "s*[" + Q + '"]')

# The text of an <OptionValues> entry reaches the page through gettext, but most of this
# model's 36 entries are the driver's own name repeated - <CFontz>CFontz</CFontz>. Those
# are identifiers printed verbatim, not sentences, and cataloguing them would mean 34
# msgids whose Arabic is the Latin name back again. An entry whose text differs from its
# tag is the case where somebody wrote words, and words are what this checks.


def page_strings():
    used = set()
    calls = 0
    matched = 0
    for path in sorted(glob.glob(os.path.join(
            HERE, 'src', 'opnsense', 'mvc', 'app', 'views', 'OPNsense', '*', '*.volt'))):
        text = open(path, encoding='utf-8').read()
        calls += len(ANY_CALL.findall(text))
        raws = PATTERN.findall(text)
        matched += len(raws)
        for raw in raws:
            used.add(raw.replace(BS + Q, Q).replace(BS + BS, BS))
    return used, calls, matched


def form_strings():
    used = set()
    for path in sorted(glob.glob(os.path.join(
            HERE, 'src', 'opnsense', 'mvc', 'app', 'controllers',
            'OPNsense', '*', 'forms', '*.xml'))):
        for field in ET.parse(path).getroot().iter('field'):
            for tag in ('label', 'help', 'hint'):
                node = field.find(tag)
                if node is not None and node.text and node.text.strip():
                    used.add(node.text.strip())
    return used


def model_strings():
    used = set()
    for path in sorted(glob.glob(os.path.join(
            HERE, 'src', 'opnsense', 'mvc', 'app', 'models', 'OPNsense', '*', '*.xml'))):
        root = ET.parse(path).getroot()
        for node in root.iter('ValidationMessage'):
            if node.text and node.text.strip():
                used.add(node.text.strip())
        for options in root.iter('OptionValues'):
            for option in options:
                text = (option.text or '').strip()
                if text and text != option.tag:
                    used.add(text)
    return used


def main():
    page, calls, matched = page_strings()
    form = form_strings()
    model = model_strings()
    used = page | form | model

    catalogue = os.path.join(HERE, 'src', 'opnsense', 'scripts', 'frontpanel', 'i18n', 'ui')
    with open(os.path.join(catalogue, 'source.json'), encoding='utf-8') as handle:
        source = set(json.load(handle))
    with open(os.path.join(catalogue, 'ar_SA.json'), encoding='utf-8') as handle:
        arabic = json.load(handle)

    absent = sorted(used - source)
    stale = sorted(source - used)
    missing = sorted(k for k in source if not arabic.get(k))

    print('page: %d calls, %d distinct | form: %d | model: %d | asked for: %d'
          % (calls, len(page), len(form), len(model), len(used)))
    print('catalogued: %d | translated: %d' % (len(source), len(arabic)))

    problems = 0

    if calls != matched:
        # A call the pattern cannot read is a string nobody is checking. It has never
        # happened here, and it would be invisible if it did.
        print('lang._() calls not readable by this checker: %d' % (calls - matched))
        problems += 1

    print('asked for but not catalogued: %d' % len(absent))
    for key in absent:
        print('   + ' + key[:100])
    problems += len(absent)

    print('catalogued but untranslated: %d' % len(missing))
    for key in missing:
        print('   ? ' + key[:100])
    problems += len(missing)

    # Not counted as a problem. A msgid nobody asks for costs a line in a JSON file; a
    # msgid nobody translated costs an English sentence in the middle of an Arabic page.
    # Only one of those is worth stopping a build for, and a string temporarily commented
    # out of the page is a normal thing to be in the middle of.
    print('catalogued but unused: %d' % len(stale))
    for key in stale:
        print('   - ' + key[:100])

    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
