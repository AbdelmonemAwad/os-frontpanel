<?php

/*
 * Copyright (C) 2026 Abdelmonem Awad <eg2@live.com>
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice,
 *    this list of conditions and the following disclaimer.
 *
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS "AS IS" AND ANY
 * EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 * WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 * DISCLAIMED. IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE FOR ANY
 * DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
 * (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 * LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
 * ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
 * THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

/*
 * How the front panel comes up at boot, and why this file exists.
 *
 * The daemon is started by an rc.d script, and the first version of this plugin left its switch
 * in /usr/local/etc/rc.conf.d/frontpanel for /etc/rc to read. Measured on two appliances: nothing
 * reads it. OPNsense starts a plugin's daemons from rc.bootup through plugins_configure('bootup'),
 * which calls the 'bootup' tasks a plugin returns from its _configure() - and a plugin without one
 * is a plugin whose panel is dark after every reboot until somebody opens the page and presses
 * Start. So the start is here, where OPNsense looks for it, guarded by the one setting that
 * decides it; the rc.conf.d switch stays for whoever runs the script by hand.
 */

function frontpanel_enabled()
{
    $model = new \OPNsense\FrontPanel\FrontPanel();
    return (string)$model->general->enabled == '1';
}

function frontpanel_services()
{
    $services = [];

    if (!frontpanel_enabled()) {
        return $services;
    }

    $services[] = [
        'description' => gettext('Front panel (LCDd and the screen client)'),
        'configd' => [
            'restart' => ['frontpanel restart'],
            'start' => ['frontpanel start'],
            'stop' => ['frontpanel stop'],
        ],
        'name' => 'frontpanel',
        'pidfile' => '/var/run/frontpanel/LCDd.pid',
    ];

    return $services;
}

function frontpanel_configure()
{
    return [
        'bootup' => ['frontpanel_configure_do'],
    ];
}

function frontpanel_configure_do($verbose = false)
{
    if (!frontpanel_enabled()) {
        return;
    }

    if ($verbose) {
        echo 'Starting the front panel...';
        flush();
    }

    configd_run('frontpanel start');

    if ($verbose) {
        echo "done.\n";
    }
}
