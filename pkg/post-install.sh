#!/bin/sh
# Copyright (C) 2026 Abdelmonem Awad <eg2@live.com>. BSD 2-Clause License.
#
# Run by pkg(8) after the files of os-frontpanel are in place, on install and on upgrade
# alike. tools/make-package.sh inlines it into the package manifest.
#
# Two things this script deliberately does not do, and they are the same two that
# install/install.sh refuses:
#
#   It does not start the service. A plugin that begins writing to a serial port the
#   moment it is installed is a plugin that can take somebody else's console away, on a
#   machine whose panel it has never seen. The panel stays dark until somebody turns it
#   on from the page.
#
#   It does not write an LCDd configuration. That file is generated from the settings, by
#   the service, at the moment it starts - the only arrangement in which what is on disk
#   and what is on the panel cannot disagree.
#
# install/install.sh also checks for /usr/local/sbin/LCDd and refuses without it. That
# check is not here because it cannot fail here: PLUGIN_DEPENDS names lcdproc, the
# manifest carries it as a dependency, and pkg will not put this package on a machine
# without it. The hand installation needed the check precisely because it had no manifest.
#
# Not here either: the chmod lines (pkg set every mode from the plist and recorded it, and
# setting them again would make pkg check -s report this package as altered), the php -l /
# XML / JSON / py_compile checks (they belong to the source tree, and the checks workflow
# runs them on every change - by the time this runs the files are installed and a failure
# can undo nothing), and the two rm lines for the menu and ACL caches (rc.configure_plugins
# POST_INSTALL below calls system_cache_flush(), which drops those two and also the model
# caches and the compiled Volt templates).

# configd reads actions_frontpanel.conf once, at start.
if [ -f /usr/local/etc/rc.d/configd ]; then
	/usr/local/etc/rc.d/configd restart
fi

# Where the generated LCDd configuration will land. Made now, empty, so that the first
# start has somewhere to write and does not have to decide what mode the directory should
# have while it is already half way through starting a daemon.
install -d -o root -g wheel -m 0750 /usr/local/etc/frontpanel

# LCDd and the screen client write here. 0750 because the LCDd log carries the driver's
# own report of what it found on the serial port, which is diagnostic detail about the
# hardware and not something every account on the machine needs.
install -d -o root -g wheel -m 0750 /var/log/frontpanel

# The screen client's own record of which keys have reached it - the half of the key
# report that outlives a restart. install -d repairs the mode on an upgrade rather than
# leaving whatever an earlier version chose.
install -d -o root -g wheel -m 0750 /var/db/frontpanel

# The switch /etc/rc consults at boot. Written once, off, and never written again: whether
# this machine brings the panel up by itself is a decision somebody made, and an update
# must not undo it. rc.subr's own enable and disable edit this same file in place
# afterwards, which is what configctl frontpanel enable does.
RCCONF=/usr/local/etc/rc.conf.d/frontpanel
if [ ! -f "${RCCONF}" ]; then
	install -d -o root -g wheel -m 0755 /usr/local/etc/rc.conf.d
	{
		echo '# Whether this machine brings the front panel up at boot.'
		echo '# Written once by the package; changed with: configctl frontpanel enable'
		echo 'frontpanel_enable="NO"'
	} > "${RCCONF}"
	chmod 644 "${RCCONF}"
fi

if [ -f /usr/local/opnsense/mvc/script/run_migrations.php ]; then
	/usr/local/opnsense/mvc/script/run_migrations.php OPNsense/FrontPanel
fi

# Put the plugin in config.xml's system/firmware/plugins list, which is where OPNsense
# keeps the plugins it considers managed; without it System > Firmware > Plugins shows
# this as an installed package that nothing configured. register.php reads the version
# marker the package ships at /usr/local/opnsense/version/frontpanel and refuses anything
# whose name does not start with os-. It is idempotent.
if [ -x /usr/local/opnsense/scripts/firmware/register.php ]; then
	/usr/local/opnsense/scripts/firmware/register.php install os-frontpanel > /dev/null 2>&1 || true
fi

if [ -f /usr/local/etc/rc.configure_plugins ]; then
	echo "Reloading plugin configuration"
	/usr/local/etc/rc.configure_plugins POST_INSTALL
fi

# GUI strings for every installed language. Guarded rather than assumed: a build of this
# plugin that ships no catalogue of its own is a perfectly good plugin, and the install
# should not complain because there was nothing to merge. The webgui is restarted only
# when there was something to add, because a restart takes away every logged-in session's
# php worker.
if [ -x /usr/local/opnsense/scripts/frontpanel/merge_ui_translations.py ]; then
	ADDED=$(/usr/local/opnsense/scripts/frontpanel/merge_ui_translations.py 2> /dev/null) || ADDED=
	echo "translated strings added: ${ADDED:-0}"
	if [ -n "${ADDED}" ] && [ "${ADDED}" != "0" ]; then
		# absolute, because a pkg script does not necessarily inherit a PATH with
		# /usr/local/sbin in it - which is why os-vnstat's own post-install calls
		# /usr/local/sbin/configctl by its full path too
		[ -f /usr/local/sbin/configctl ] &&
		    /usr/local/sbin/configctl webgui restart > /dev/null 2>&1 || true
	fi
fi

echo "Front Panel installed: the page is at System > Front Panel"

# An upgrade leaves the running service running the code it started with - python has
# already read the old files into memory - and this script will not restart it uninvited,
# because a restart blanks the panel for a second or two and the owner may well be
# standing in front of it. Say so and let them choose the moment.
if [ -x /usr/local/etc/rc.d/frontpanel ] && /usr/local/etc/rc.d/frontpanel status > /dev/null 2>&1; then
	echo "the panel is still running the code that was installed before this one;"
	echo "restart it from the page, or with:  configctl frontpanel restart"
else
	echo "nothing is running yet: the panel stays dark until it is enabled on that page"
fi
