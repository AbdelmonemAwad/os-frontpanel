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

namespace OPNsense\FrontPanel\Api;

use OPNsense\Base\ApiMutableServiceControllerBase;
use OPNsense\Core\Backend;

/**
 * Start, stop and look at the screen client, and the three questions the settings page asks that
 * a plain service controller has no answer for: what the panel would be showing right now, what
 * the driver has reported from the keys, and whether a line put on the panel by hand arrives.
 */
class ServiceController extends ApiMutableServiceControllerBase
{
    protected static $internalServiceName = 'frontpanel';
    protected static $internalServiceClass = '\OPNsense\FrontPanel\FrontPanel';
    protected static $internalServiceEnabled = 'general.enabled';

    /**
     * The longest line the test will put on the panel. The display cuts at its own width long
     * before this, and the message screen in the model stops at the same 64 characters, so this
     * is not a limit anybody meets by accident - it is here so that a request with a novel in it
     * is refused before it reaches a command line.
     */
    private const TEST_TEXT_MAX = 64;

    /**
     * LCDd reads its configuration once, when it starts. Every speed on the settings page is a
     * line in that file, so there is no such thing as reloading one of them into a running
     * server: applying a change means writing the file again and starting over.
     */
    protected function reconfigureForceRestart()
    {
        return 1;
    }

    /**
     * Applying the settings also decides whether the panel comes back after a reboot.
     *
     * The framework's own reconfigure starts and stops the service and no more; what a machine
     * does at boot is written in rc.conf.d, and rc.subr is the thing that edits it. Nothing else
     * on this page would ever set that switch, so a panel turned on here would light up now and
     * be dark after the next reboot - which is exactly the kind of difference nobody attributes
     * to the right cause three weeks later. The switch is set first, so that it is right even if
     * the start that follows it fails.
     */
    public function reconfigureAction()
    {
        if ($this->request->isPost()) {
            (new Backend())->configdRun(
                'frontpanel ' . ($this->serviceEnabled() ? 'enable' : 'disable')
            );
        }

        return parent::reconfigureAction();
    }

    private function run($action, $params = [])
    {
        return (new Backend())->configdpRun('frontpanel ' . $action, $params, false, 60);
    }

    /**
     * Every one of these actions answers in JSON, and a script that could not run answers with
     * nothing at all. Saying so in the shape the page already understands is better than letting
     * it decide for itself what an empty string meant.
     */
    private function response($output)
    {
        $response = json_decode($output, true);
        return is_array($response)
            ? $response
            : ['status' => 'failed', 'detail' => gettext('No response from the front panel script.')];
    }

    /**
     * What each enabled screen would put on the panel this second.
     *
     * Handed back as the script wrote it, lines and all, without being cut to the width of the
     * display. The cutting is the page's job, and it is the whole point of the preview: a line
     * trimmed here would arrive looking like it fits.
     */
    public function previewAction()
    {
        return $this->response($this->run('preview'));
    }

    /**
     * The state of things around the panel: the serial ports this machine has, whether the
     * keypad is being polled at all, and what the driver has reported from it.
     *
     * The keys are proven on the reference appliance and on nobody else's, so this answer is
     * written to read well when nothing has arrived at all: on hardware the owner has not
     * measured, "the driver has reported nothing" is the finding, not an empty box.
     */
    public function diagnosticsAction()
    {
        return $this->response($this->run('diagnostics'));
    }

    /**
     * Put one line on the panel, hold it for a moment, and give the panel back.
     *
     * Nothing here touches the serial port: the line goes to LCDd like every other screen, which
     * is also why it is refused while the service is down - there would be nobody to send it to,
     * and "it did not work" is a worse answer than saying which part is not running.
     */
    public function testAction()
    {
        if (!$this->request->isPost()) {
            return ['status' => 'failed'];
        }
        if ($this->statusAction()['status'] !== 'running') {
            return ['status' => 'failed',
                    'detail' => gettext('The front panel service is not running, so there is nothing to send the line to.')];
        }
        /* Read without a sanitiser, on purpose. The framework's 'string' filter is
           htmlspecialchars(), which is the right thing for a value on its way into a page and
           the wrong thing for a line on its way to a character display: an apostrophe would
           arrive at the panel as six columns of &#039; and an ampersand as five of &amp;, on a
           screen sixteen columns wide. Nothing downstream needs the escaping either - the value
           is checked below, and configd quotes every parameter it passes to a script - so the
           line is carried as the owner typed it.

           What arrives is therefore whatever the JSON body held. A body that sent something
           other than a string - a list, say - reaches the check below as something it will not
           accept, which is the point of testing the type there rather than trusting the read. */
        $text = $this->request->getPost('text', null, '');
        if ($text !== '' && !$this->validText($text)) {
            return ['status' => 'failed',
                    'detail' => sprintf(
                        gettext('The test line must be at most %d characters and may not contain control characters.'),
                        self::TEST_TEXT_MAX
                    )];
        }
        /* An empty line is not an error: the script has a line of its own for exactly this, and
           somebody who only wants to know whether the panel answers should not have to invent
           words first. */
        return $this->response($this->run('test', [$text]));
    }

    /**
     * A line meant for a character panel. Length is counted in characters rather than bytes,
     * because a panel counts cells; control characters are refused because the panel has no
     * glyph for any of them and a newline in the middle of a line means nothing to a display
     * that is told where each row starts.
     *
     * The match is read as "found nothing to object to" rather than as "did not find one": a
     * subject that is not valid UTF-8 makes the test fail outright rather than return an answer,
     * and text that cannot even be decoded is exactly the text this is here to stop.
     */
    private function validText($text)
    {
        return is_string($text)
            && mb_strlen($text) <= self::TEST_TEXT_MAX
            && preg_match('/[\p{C}]/u', $text) === 0;
    }
}
