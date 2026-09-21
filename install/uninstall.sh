#!/bin/sh
# Copyright (C) 2026 Abdelmonem Awad <eg2@live.com>. BSD 2-Clause License.
#
# Remove the Front Panel plugin files. The settings stay in config.xml and the switch stays
# in /usr/local/etc/rc.conf.d/frontpanel, so a machine that had the panel running comes back
# with it running after a reinstall, set up the way it was left.

# Stopped first, while there is still an rc script to stop it with, and stopped properly: the
# client is given its few seconds to finish the line it is on and clear the display, so the
# appliance is not left standing in the rack showing the last frame of a plugin that is no
# longer installed. onestop rather than stop because the switch may already have been turned
# off, and a stop has to stop.
if [ -x /usr/local/etc/rc.d/frontpanel ]; then
    /usr/local/etc/rc.d/frontpanel onestop || true
fi

rm -f /usr/local/etc/rc.d/frontpanel
rm -f /usr/local/etc/newsyslog.conf.d/frontpanel
rm -f /usr/local/opnsense/service/conf/actions.d/actions_frontpanel.conf
rm -rf /usr/local/opnsense/scripts/frontpanel
rm -rf /usr/local/opnsense/mvc/app/models/OPNsense/FrontPanel
rm -rf /usr/local/opnsense/mvc/app/controllers/OPNsense/FrontPanel
rm -rf /usr/local/opnsense/mvc/app/views/OPNsense/FrontPanel

# The generated LCDd configuration is not a setting. It is written from config.xml every time
# the service starts, so nothing is lost by removing it - and left behind it would be a file
# naming a serial port that nothing on this machine opens any more.
rm -rf /usr/local/etc/frontpanel

# The pidfiles of a service that has just been stopped, in case it had to be killed and
# daemon(8) never got round to removing them itself.
rm -rf /var/run/frontpanel

# /var/log/frontpanel and /var/db/frontpanel are kept on purpose. Whether the panel ever lit,
# what the driver said about the serial port, and which keys ever reported are between those
# two, and that is precisely what somebody who is about to reinstall - or about to write a bug
# report - wants to read. Nothing writes either once the service is gone, so neither can grow.

service configd restart > /dev/null

# the menu and the ACL map are cached on disk for an hour each, so the menu would keep a dead
# entry until then. They live in the framework's own tempDir, which is /var/lib/php/tmp on
# 26.7 and not /tmp, so ask config.php where it is.
CONFIGPHP=/usr/local/opnsense/mvc/app/config/config.php
PHPTMP=$(php -r "echo (include '${CONFIGPHP}')->application->tempDir;" 2>/dev/null)
PHPTMP=${PHPTMP:-/var/lib/php/tmp}
rm -f "${PHPTMP}/opnsense_menu_cache.xml" "${PHPTMP}/opnsense_acl_cache.json"

configctl webgui restart > /dev/null 2>&1 || true

# the GUI strings merged into the gettext catalogs are left where they are: they are only
# ever read by msgid, and the next core update replaces those catalogs anyway
echo "Front Panel removed; settings in config.xml and the log in /var/log/frontpanel kept"
