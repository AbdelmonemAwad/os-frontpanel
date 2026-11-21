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
 * THIS SOFTWARE IS PROVIDED ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES,
 * INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
 * AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 * AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
 * OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 */

namespace OPNsense\FrontPanel\Migrations;

use OPNsense\Base\BaseModelMigration;
use OPNsense\Core\Config;

/**
 * 1.3.0: the throughput screen's interface became a choice of assigned interfaces, several
 * allowed, where it was one kernel name typed into a box.
 *
 * Each name saved before is carried over by what it was:
 *
 *  - empty: nothing to do. Empty still means the WAN;
 *  - the device behind an assigned interface (igb0 behind wan, say): that interface, which is
 *    what the panel measured and now names by its description as before;
 *  - a name no assigned interface owns: kept in throughput_dev, which the page does not show
 *    and the screen goes on measuring while nothing is chosen in the list. The list cannot hold
 *    it, and dropping it would quietly move the screen to the WAN on a firewall whose owner had
 *    picked another port on purpose. Choosing an interface in the list replaces it.
 *
 * config.py reads an old value the same way (screens.throughput_targets), so the panel measures
 * the same port before this has run as after.
 */
class M1_3_0 extends BaseModelMigration
{
    public function run($model)
    {
        $saved = Config::getInstance()->object();
        if (!isset($saved->OPNsense->FrontPanel->general->throughput_if)) {
            return;
        }
        $old = trim((string)$saved->OPNsense->FrontPanel->general->throughput_if);
        if ($old === '') {
            return;
        }

        $owner = [];
        if (isset($saved->interfaces)) {
            foreach ($saved->interfaces->children() as $role => $node) {
                $device = trim((string)$node->if);
                if ($device !== '' && !isset($owner[$device])) {
                    $owner[$device] = $role;
                }
            }
        }

        $general = $model->general;
        if (isset($owner[$old])) {
            $general->throughput_if = $owner[$old];
        } elseif (isset($saved->interfaces->$old)) {
            /* already an interface's own name, such as opt1, which the old box also accepted */
            $general->throughput_if = $old;
        } else {
            $general->throughput_if = '';
            $general->throughput_dev = $old;
        }
    }
}
