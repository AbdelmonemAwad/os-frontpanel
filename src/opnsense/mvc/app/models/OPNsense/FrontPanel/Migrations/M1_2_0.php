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
 * 1.2.0: the message became two lines, one to a row of the display, and both have a default.
 *
 * The first line is the field the single line always was, so whatever is in it stays there. What
 * this decides is the rest, from what was saved before:
 *
 *  - nothing saved at all: the model's defaults stand, both lines, and there is nothing to do;
 *  - a message the owner wrote: it stays the first line, and the second is left empty rather
 *    than given the default. A panel that showed the owner's words yesterday must not show an
 *    address beside them today that nobody asked for;
 *  - the message saved empty, which is how every version before this one shipped it: nobody
 *    wrote one, so both lines take the defaults, as they would on a machine that never saved.
 *
 * config.py reads config.xml without the model and decides the same three cases the same way, so
 * the panel shows the same lines before this has run as after.
 */
class M1_2_0 extends BaseModelMigration
{
    public function run($model)
    {
        $saved = Config::getInstance()->object();
        if (!isset($saved->OPNsense->FrontPanel->general->message)) {
            return;
        }

        $general = $model->general;
        if (trim((string)$saved->OPNsense->FrontPanel->general->message) !== '') {
            $general->message2 = '';
        } else {
            $general->message->applyDefault();
            $general->message2->applyDefault();
        }
    }
}
