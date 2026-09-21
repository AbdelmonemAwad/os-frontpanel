#!/bin/sh
# Copyright (C) 2026 Abdelmonem Awad <eg2@live.com>. BSD 2-Clause License.
#
# Run by pkg(8) after the files of os-frontpanel have been removed. pkg does not run this
# during an upgrade - it runs the new post-install instead - so everything here may assume
# the plugin is going for good. The panel was already stopped, by pkg/pre-deinstall.sh,
# while there was still an rc script to stop it with.
#
# pkg has already removed every file the package owns and every directory under them that
# it created and that is now empty, so none of install/uninstall.sh's rm lines are
# repeated here.

# The generated LCDd configuration is not a setting: it is written from config.xml every
# time the service starts, so nothing is lost by removing it - and left behind it would be
# a file naming a serial port that nothing on this machine opens any more.
rm -rf /usr/local/etc/frontpanel

# The pidfiles of a service that has just been stopped, in case it had to be killed and
# daemon(8) never got round to removing them itself.
rm -rf /var/run/frontpanel

# Take the plugin back out of config.xml's system/firmware/plugins. Left in, it would be a
# plugin OPNsense believes it is managing and cannot find, and the next plugin sync would
# try to install it from a repository that has never heard of it.
if [ -x /usr/local/opnsense/scripts/firmware/register.php ]; then
	/usr/local/opnsense/scripts/firmware/register.php remove os-frontpanel > /dev/null 2>&1 || true
fi

# actions_frontpanel.conf is gone; configd is still holding it.
if [ -f /usr/local/etc/rc.d/configd ]; then
	/usr/local/etc/rc.d/configd restart
fi

# system_cache_flush(): without it the menu keeps a dead entry and the user manager keeps
# an ACL tag pointing at a page that is not there, for up to an hour each.
if [ -f /usr/local/etc/rc.configure_plugins ]; then
	echo "Reloading plugin configuration"
	/usr/local/etc/rc.configure_plugins POST_DEINSTALL
fi

# Two things are kept on purpose, and both are named here rather than left for somebody to
# find later. (Merged GUI strings are not among them: this plugin ships no catalogue of
# its own today, so there is nothing of its in anyone else's .mo files. If it ever gets
# one, what os-linkhealth's post-deinstall says about them will apply here too.)
#
#   /var/log/frontpanel and /var/db/frontpanel - whether the panel ever lit, what the
#   driver said about the serial port, and which keys ever reported are between those two,
#   and that is precisely what somebody about to reinstall, or about to write a bug
#   report, wants to read. Nothing writes either once the service is gone, so neither can
#   grow.  Remove them with:  rm -rf /var/log/frontpanel /var/db/frontpanel
#
#   /usr/local/etc/rc.conf.d/frontpanel - three lines saying whether this machine brings
#   the panel up at boot. It is a decision somebody made; rc ignores it while there is no
#   rc.d/frontpanel to go with it, and a reinstall finds the machine set up as it was
#   left.  Remove it with:  rm -f /usr/local/etc/rc.conf.d/frontpanel
echo "Front Panel removed; the settings in config.xml and the log in /var/log/frontpanel are kept"
