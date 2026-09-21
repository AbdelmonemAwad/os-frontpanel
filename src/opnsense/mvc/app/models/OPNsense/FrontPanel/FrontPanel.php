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

namespace OPNsense\FrontPanel;

use OPNsense\Base\BaseModel;
use OPNsense\Base\Messages\Message;

class FrontPanel extends BaseModel
{
    public function performValidation($validateFullModel = false)
    {
        $messages = parent::performValidation($validateFullModel);

        $general = $this->general;
        if (!$validateFullModel && !$general->isFieldChanged()) {
            return $messages;
        }

        $rotation = $general->screens->getValues();
        $message = trim((string)$general->message);
        $throughput_if = (string)$general->throughput_if;

        /* The message screen with no line yet is deliberately NOT a complaint, and this is
           worth writing down because it looks like one that was forgotten.

           A screen with nothing to say is skipped, and the preview says which and why - the
           ports screen does exactly that on a firewall without os-linkhealth, and the settings
           page promises as much in as many words beside the rotation. The shipped rotation
           contains every screen, including this one, and the shipped message is empty; refusing
           the save would therefore refuse the settings this plugin installs with, on the first
           visit, before the owner had written a single character. Every validation message here
           stops a save - there is no channel for a remark - so the empty message belongs in the
           preview, where it already is, and not here.

           The other way round is a real mistake and the commoner one: a line written, saved,
           and never shown, because the screen that would have shown it is not in the rotation.
           Nothing else on the page would ever mention it. */
        if (!in_array('message', $rotation) && $message !== '') {
            $messages->appendMessage(new Message(
                gettext('The message screen is not in the rotation, so this line would never be shown.'),
                'general.message'
            ));
        }

        /* An interface chosen for a screen nobody is showing. Left empty the throughput screen
           measures the WAN on purpose, so the absence of this is never a complaint - only its
           presence without the screen that reads it. */
        if (!in_array('throughput', $rotation) && $throughput_if !== '') {
            $messages->appendMessage(new Message(
                gettext('The throughput screen is not in the rotation, so nothing would measure this interface.'),
                'general.throughput_if'
            ));
        }

        return $messages;
    }
}
