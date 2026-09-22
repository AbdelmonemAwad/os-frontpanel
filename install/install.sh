#!/bin/sh
# Copyright (C) 2026 Abdelmonem Awad <eg2@live.com>. BSD 2-Clause License.
#
# Install the Front Panel plugin from a copy of this repository on the firewall:
#   sh install/install.sh
#
# Safe to run again after an update: the settings in config.xml are kept, and so is the
# switch in /usr/local/etc/rc.conf.d/frontpanel.
#
# Two things this script deliberately does not do.
#
# It does not start the service. A plugin that begins writing to a serial port the moment it
# is installed is a plugin that can take somebody else's console away, on a machine whose
# panel it has never seen. The panel stays dark until somebody turns it on from the page.
#
# It does not write an LCDd configuration either. That file is generated from the settings,
# by the service, at the moment it starts - which is the only arrangement in which what is on
# disk and what is on the panel cannot disagree.

set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
CONFIGPHP=/usr/local/opnsense/mvc/app/config/config.php
RCCONF=/usr/local/etc/rc.conf.d/frontpanel

# LCDproc is what actually drives the panel; this plugin only configures it and feeds it
# lines. The Makefile declares the dependency, so a package install already has it, but a
# repository unpacked by hand does not - and the first start would then fail with a missing
# file and no explanation. Say it here instead, with the command that fixes it.
if [ ! -x /usr/local/sbin/LCDd ]; then
    echo "LCDproc is not installed: /usr/local/sbin/LCDd is missing."
    echo "install it first with:  pkg install lcdproc"
    exit 1
fi

# plugin files: src/ maps to /usr/local
cp -R "${HERE}/src/" /usr/local/

# frontpanel.py is run by the rc script and by configd, so it needs the bit; the modules
# beside it are imported rather than executed, and panels.json is only ever read. Giving the
# whole directory the same treatment as os-linkhealth does keeps a new module from arriving
# without the bit and failing an hour later for a reason nobody can see.
find /usr/local/opnsense/scripts/frontpanel -type f -name '*.py' -exec chmod 755 {} +
find /usr/local/opnsense/scripts/frontpanel -type f ! -name '*.py' -exec chmod 644 {} +
chmod 755 /usr/local/etc/rc.d/frontpanel
# the boot hook that puts the GUI strings back after a core update has replaced the
# catalogues; /etc/rc runs it as a program, so it needs the bit like the rc script above
chmod 755 /usr/local/etc/rc.syshook.d/start/63-frontpanel
chmod 644 /usr/local/etc/newsyslog.conf.d/frontpanel
chmod 644 /usr/local/opnsense/service/conf/actions.d/actions_frontpanel.conf

# Where the generated LCDd configuration will land. The directory is made now, empty, so
# that the first start has somewhere to write and does not have to decide what mode it should
# have while it is already half way through starting a daemon.
install -d -o root -g wheel -m 0750 /usr/local/etc/frontpanel

# LCDd and the screen client write here. 0750 because the LCDd log carries the driver's own
# report of what it found on the serial port, which is diagnostic detail about the hardware
# and not something every account on the machine needs.
install -d -o root -g wheel -m 0750 /var/log/frontpanel

# The screen client's own record of which keys have reached it. It is the half of the key
# report that outlives a restart - the other half is read back out of LCDd's log, which begins
# again every time the service starts. Made now, with the same mode as the log beside it, so
# that the first press has somewhere to be written down, and install -d repairs the mode on a
# second run rather than leaving whatever an earlier version chose.
install -d -o root -g wheel -m 0750 /var/db/frontpanel

# Everything that has to parse is checked while only files have been touched: a syntax error
# must stop the install here rather than after configd has been told to reload it. php -l
# writes the parse error to its own stdout, so it cannot simply be discarded - the install
# would then stop without ever saying which file was wrong.
for f in $(find "${HERE}/src" -name '*.php'); do
    REPORT=$(php -l "$f" 2>&1) || { echo "${REPORT}"; exit 1; }
done
# the model, the form, the ACL and the menu are all XML, read by the GUI through the caches
# dropped below; one malformed file there takes the page with it
for f in $(find "${HERE}/src" -name '*.xml'); do
    python3 -c 'import sys, xml.etree.ElementTree as ET; ET.parse(sys.argv[1])' "$f" ||
        { echo "malformed XML: $f"; exit 1; }
done
for f in $(find /usr/local/opnsense/scripts/frontpanel -name '*.py'); do
    python3 -m py_compile "$f"
done
# panels.json is the appliance table: the driver and the options proposed for a machine that
# matches. A broken one would only surface when somebody opened the page looking for help
for f in $(find /usr/local/opnsense/scripts/frontpanel -name '*.json'); do
    python3 -c 'import json, sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$f" ||
        { echo "malformed JSON: $f"; exit 1; }
done
# The rc script is checked too, and for a harder reason than the rest: it is the one file
# that, broken, leaves a panel that cannot be started and - worse - cannot be stopped either.
# sh -n parses it without running a line of it.
sh -n /usr/local/etc/rc.d/frontpanel || { echo "the rc script does not parse"; exit 1; }

# The switch /etc/rc consults at boot. It is written once, off, and never written again by
# this script: whether this machine brings the panel up by itself is a decision somebody made,
# and an update must not undo it. rc.subr's own enable and disable edit this same file in
# place afterwards, which is what configctl frontpanel enable does.
if [ ! -f "${RCCONF}" ]; then
    install -d -o root -g wheel -m 0755 /usr/local/etc/rc.conf.d
    {
        echo '# Whether this machine brings the front panel up at boot.'
        echo '# Written once by the installer; changed with: configctl frontpanel enable'
        echo 'frontpanel_enable="NO"'
    } > "${RCCONF}"
    chmod 644 "${RCCONF}"
fi

# reload configd so it picks up the new actions
service configd restart > /dev/null

# The menu and the ACL map are cached on disk for an hour each, so until they are dropped the
# new page is missing from the menu and its ACL tag is unknown to the user manager. Those
# caches are not in /tmp: they sit in the framework's own tempDir, which is /var/lib/php/tmp
# on 26.7, so ask config.php where it is instead of writing down a path that has already
# moved once.
PHPTMP=$(php -r "echo (include '${CONFIGPHP}')->application->tempDir;" 2>/dev/null) || PHPTMP=''
PHPTMP=${PHPTMP:-/var/lib/php/tmp}
rm -f "${PHPTMP}/opnsense_menu_cache.xml" "${PHPTMP}/opnsense_acl_cache.json"

# GUI strings for every installed language, then reload php so the new catalogs are used.
# Guarded rather than assumed: a build of this plugin that ships no catalogue of its own is a
# perfectly good plugin, and the install should not stop because there was nothing to merge.
if [ -x /usr/local/opnsense/scripts/frontpanel/merge_ui_translations.py ]; then
    echo "translated strings added: $(/usr/local/opnsense/scripts/frontpanel/merge_ui_translations.py)"
fi
configctl webgui restart > /dev/null 2>&1 || true

echo "Front Panel installed: the page is at System > Front Panel"

# An update leaves the running service running the code it started with - python has already
# read the old files into memory - and this script will not restart it uninvited, because a
# restart blanks the panel for a second or two and the owner may well be standing in front of
# it. Say so and let them choose the moment.
if /usr/local/etc/rc.d/frontpanel status > /dev/null 2>&1; then
    echo "the panel is still running the code that was installed before this one;"
    echo "restart it from the page, or with:  configctl frontpanel restart"
else
    echo "nothing is running yet: the panel stays dark until it is enabled on that page"
fi
