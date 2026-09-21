#!/bin/sh
# Copyright (C) 2026 Abdelmonem Awad <eg2@live.com>. BSD 2-Clause License.
#
# Run by pkg(8) BEFORE the files of os-frontpanel are removed, and that is the whole
# reason this file exists rather than being three more lines in post-deinstall: the rc
# script that stops the panel is itself one of the packaged files. By post-deinstall time
# /usr/local/etc/rc.d/frontpanel is gone and the panel is still lit, still being written
# to by a python process nothing on the machine can now stop politely.
#
# onestop rather than stop, because the boot switch may be off and a stop has to stop. The
# client is given its few seconds to finish the line it is on and clear the display, so
# the appliance is not left standing in the rack showing the last frame of a plugin that
# is no longer installed.

# pkg runs the OLD package's pre-deinstall in the middle of an upgrade too. Stopping there
# would blank the panel every single time the plugin is updated, which is not what an
# update should cost. PKG_UPGRADE is set in exactly that case and in no other.
if [ -n "${PKG_UPGRADE}" ]; then
	exit 0
fi

if [ -x /usr/local/etc/rc.d/frontpanel ]; then
	/usr/local/etc/rc.d/frontpanel onestop || true
fi
