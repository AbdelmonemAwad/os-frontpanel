#!/bin/sh
#-
# SPDX-License-Identifier: BSD-2-Clause
# Copyright (c) 2026 Abdelmonem Awad <eg2@live.com>
#
# Turn the front panel on without the settings page - for an image that installs the plugin at
# first boot and is meant to leave the appliance's panel working - and ONLY where the appliance
# table has an entry for this machine that somebody has confirmed on the hardware.
#
# That condition is the plugin's own rule, kept rather than worked around. A proposal is applied
# by the owner pressing Apply on the settings page, "because a wrong driver writing to the wrong
# serial port is not a mistake a plugin should make on its own initiative" (frontpanel.py, panels).
# A confirmed entry is the one case where that mistake has already been ruled out: somebody saw
# the panel draw text with exactly these settings. Anything less - no match, the family entry, an
# unconfirmed one - is left off, with the reason printed, and the page still offers it.
#
# What it sets is what Apply sets: the driver, the connection, the device, the size and the keypad
# from the entry; then enabled, the boot switch in rc.conf.d, and LCDd started - what the page's
# Save does after Apply. Run it again and it does the same again; nothing else is touched.
#
#   install/enable.sh        exit 0 whether it turned the panel on or said why not
set -u

if [ ! -x /usr/local/sbin/LCDd ]; then
    echo "front panel left off: LCDproc is not installed (/usr/local/sbin/LCDd)"
    exit 0
fi

REPORT=$(/usr/local/bin/python3 /usr/local/opnsense/scripts/frontpanel/frontpanel.py panels 2>/dev/null)
if [ -z "${REPORT}" ]; then
    echo "front panel left off: the appliance table could not be read"
    exit 0
fi

# The decision and the settings in one place, through the plugin's own model, so the values are
# validated exactly as the page's would be.
FP_REPORT=${REPORT} /usr/local/bin/php -r '
require_once "/usr/local/opnsense/mvc/script/load_phalcon.php";
$r = json_decode(getenv("FP_REPORT"), true);
if (!is_array($r) || ($r["status"] ?? "") !== "ok") { echo "front panel left off: no answer from the appliance table\n"; exit(0); }
$panel = is_array($r["panel"] ?? null) ? $r["panel"] : [];
$name = $r["match"] ?? "generic";
if (empty($r["matched"])) { echo "front panel left off: no entry in the appliance table matches this machine\n"; exit(0); }
if (empty($panel["confirmed"])) { echo "front panel left off: the entry for this machine (" . $name . ") has not been confirmed on the hardware\n"; exit(0); }
$opt = is_array($panel["options"] ?? null) ? $panel["options"] : [];
$m = new \OPNsense\FrontPanel\FrontPanel();
if (!empty($panel["driver"])) { $m->general->driver = (string)$panel["driver"]; }
if (!empty($opt["ConnectionType"])) { $m->general->connection = (string)$opt["ConnectionType"]; }
if (!empty($opt["Device"])) { $m->general->device = (string)$opt["Device"]; }
if (!empty($opt["Size"])) { $m->general->size = (string)$opt["Size"]; }
if (isset($opt["Keypad"])) { $m->general->keypad = ((string)$opt["Keypad"] === "yes") ? "1" : "0"; }
$m->general->enabled = "1";
$bad = [];
foreach ($m->performValidation() as $msg) { $bad[] = $msg->getField() . ": " . $msg->getMessage(); }
if ($bad) { echo "front panel left off: the entry for " . $name . " does not validate - " . implode("; ", $bad) . "\n"; exit(0); }
$m->serializeToConfig();
\OPNsense\Core\Config::getInstance()->save();
echo "front panel turned on from the confirmed entry " . $name . ": " . $m->general->driver . ", " .
    $m->general->connection . " on " . $m->general->device . ", " . $m->general->size . "\n";
exit(10);
'
[ $? -eq 10 ] || exit 0

configctl frontpanel enable > /dev/null 2>&1
configctl frontpanel stop > /dev/null 2>&1
configctl frontpanel start > /dev/null 2>&1
exit 0
