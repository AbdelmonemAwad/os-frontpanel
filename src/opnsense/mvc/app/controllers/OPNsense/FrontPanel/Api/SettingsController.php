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

use OPNsense\Base\ApiMutableModelControllerBase;
use OPNsense\Core\Backend;

/**
 * The settings live in one container and are saved in one go; the rotation is part of it rather
 * than a grid of its own, because it is a short list whose order matters, read back out of
 * config.xml by a Python script that expects to find it exactly there.
 *
 * The buttons are the one grid: a row per key, edited one at a time, filled from what this
 * appliance is known to have, and given the codes the panel itself sends when asked to learn them.
 */
class SettingsController extends ApiMutableModelControllerBase
{
    protected static $internalModelName = 'frontpanel';
    protected static $internalModelClass = '\OPNsense\FrontPanel\FrontPanel';

    public function searchButtonAction()
    {
        return $this->searchBase(
            'buttons.button',
            ['enabled', 'key', 'label', 'code', 'action', 'target'],
            'key'
        );
    }

    public function getButtonAction($uuid = null)
    {
        return $this->getBase('button', 'buttons.button', $uuid);
    }

    public function addButtonAction()
    {
        return $this->addBase('button', 'buttons.button');
    }

    public function setButtonAction($uuid)
    {
        return $this->setBase('button', 'buttons.button', $uuid);
    }

    public function delButtonAction($uuid)
    {
        return $this->delBase('buttons.button', $uuid);
    }

    public function toggleButtonAction($uuid, $enabled = null)
    {
        return $this->toggleBase('buttons.button', $uuid, $enabled);
    }

    /**
     * Add a row for every key this appliance is known to have and the grid does not list yet,
     * with the label, the code and the action the appliance table gives it. Rows already in the
     * grid are the owner's and are left exactly as they are.
     */
    public function fillButtonsAction()
    {
        if (!$this->request->isPost()) {
            return ['status' => 'failed'];
        }
        $answer = json_decode((new Backend())->configdRun('frontpanel buttons'), true);
        if (!is_array($answer) || !isset($answer['buttons'])) {
            return ['status' => 'failed', 'detail' => gettext('No response from the front panel script.')];
        }

        $mdl = $this->getModel();
        $present = [];
        foreach ($mdl->buttons->button->iterateItems() as $button) {
            $present[(string)$button->key] = true;
        }

        $added = 0;
        foreach ($answer['buttons'] as $row) {
            if (empty($row['key']) || isset($present[$row['key']])) {
                continue;
            }
            $node = $mdl->buttons->button->Add();
            $node->setNodes([
                'enabled' => '1',
                'key' => $row['key'],
                'label' => $row['label'] ?? '',
                'code' => $row['code'] ?? '',
                'action' => $row['action'] ?? 'none',
                'target' => $row['target'] ?? '',
            ]);
            $present[$row['key']] = true;
            $added++;
        }

        if ($added > 0) {
            $result = $this->validate();
            if (!empty($result['validations'])) {
                return ['status' => 'failed', 'validations' => $result['validations']];
            }
            $this->save();
        }
        return ['status' => 'ok', 'added' => $added];
    }

    /**
     * Learn each key's code from the panel, and keep what was learned in the grid.
     *
     * The script stops the panel, asks for the keys one at a time on the glass, and starts it
     * again; this writes each code it heard into that key's row, adding the row if the grid did
     * not have one. A key that was not pressed keeps whatever code it had.
     */
    public function learnButtonsAction()
    {
        if (!$this->request->isPost()) {
            return ['status' => 'failed'];
        }
        $answer = json_decode(
            (new Backend())->configdpRun('frontpanel learnkeys', [''], false, 150),
            true
        );
        if (!is_array($answer)) {
            return ['status' => 'failed', 'detail' => gettext('No response from the front panel script.')];
        }
        if (($answer['status'] ?? '') !== 'ok' || empty($answer['learned'])) {
            return $answer;
        }

        $mdl = $this->getModel();
        $rows = [];
        foreach ($mdl->buttons->button->iterateItems() as $button) {
            $rows[(string)$button->key] = $button;
        }
        $defaults = json_decode((new Backend())->configdRun('frontpanel buttons'), true);
        $by_key = [];
        foreach ((is_array($defaults) ? ($defaults['buttons'] ?? []) : []) as $row) {
            $by_key[$row['key']] = $row;
        }

        foreach ($answer['learned'] as $key => $code) {
            if (isset($rows[$key])) {
                $rows[$key]->code = $code;
                continue;
            }
            $node = $mdl->buttons->button->Add();
            $node->setNodes([
                'enabled' => '1',
                'key' => $key,
                'label' => $by_key[$key]['label'] ?? '',
                'code' => $code,
                'action' => $by_key[$key]['action'] ?? 'none',
                'target' => '',
            ]);
        }

        $result = $this->validate();
        if (!empty($result['validations'])) {
            return ['status' => 'failed', 'validations' => $result['validations']];
        }
        $this->save();
        $answer['saved'] = true;
        return $answer;
    }
}
