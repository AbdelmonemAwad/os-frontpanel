{#
 # Copyright (C) 2026 Abdelmonem Awad <eg2@live.com>
 # All rights reserved.
 #
 # Redistribution and use in source and binary forms, with or without modification,
 # are permitted provided that the following conditions are met:
 #
 # 1. Redistributions of source code must retain the above copyright notice,
 #    this list of conditions and the following disclaimer.
 #
 # 2. Redistributions in binary form must reproduce the above copyright notice,
 #    this list of conditions and the following disclaimer in the documentation
 #    and/or other materials provided with the distribution.
 #
 # THIS SOFTWARE IS PROVIDED "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
 # INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
 # AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 # AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
 # OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 # SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 # INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 # CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 # ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 # POSSIBILITY OF SUCH DAMAGE.
 #}

<script>
    $(document).ready(function () {

        /* The preview asks the firewall what every screen would say this second, so it is a live
           reading and it ages like one. Five seconds is fast enough that a throughput line moves
           while somebody watches it, and slow enough that reading this page is not itself a load
           on the machine. It only runs while the preview is on screen. */
        const PREVIEW_MS = 5000;
        /* Diagnostics change far more slowly: a serial port appears when somebody plugs an
           adapter in, and a key arrives when somebody presses one. */
        const DIAGNOSTICS_MS = 15000;

        /* LCDd names a key in its log only from this report level up - measured on this
           appliance, not assumed: at 4 it writes one line per keystroke and nothing else, and at
           5 it adds a line per frame, eight times a second, which would rotate the key history
           away in minutes. The number belongs to LCDproc, not to us, and it is repeated here so
           the page can explain a silent log instead of leaving somebody to conclude the keys are
           dead. It is the same number as REPORT_LEVEL_KEYS in config.py. */
        const KEY_REPORT_LEVEL = 4;

        let preview_doc = null;         /* the last preview, kept so the settings tab can read it */
        let diagnostics_doc = null;     /* the last diagnostics answer, for the same reason */
        let devices_drawn = '';         /* what the port list under the device box currently shows */

        /* The names of the shipped screens, translated here rather than in the script that
           generates them: a Python script on this firewall has no catalogue to translate against,
           and this page is read in Arabic. The keys are the ones the model saves and the ones
           screens.py dispatches on, so the two lists cannot drift apart without the rotation
           visibly losing a name. */
        const screen_title = {
            'identity': "{{ lang._('Name and address') }}",
            'wan': "{{ lang._('Internet') }}",
            'throughput': "{{ lang._('Throughput') }}",
            'system': "{{ lang._('Processor, memory, uptime') }}",
            'temperature': "{{ lang._('Temperature') }}",
            'ports': "{{ lang._('Port health') }}",
            'message': "{{ lang._('Message') }}"
        };

        /* What each service state means in one word, and the colour that goes with it. Turned
           off is grey and not red: a panel that was deliberately switched off is not a fault. */
        const service_text = {
            'running': "{{ lang._('running') }}",
            'stopped': "{{ lang._('stopped') }}",
            'disabled': "{{ lang._('turned off') }}",
            'unknown': "{{ lang._('unknown') }}"
        };

        const service_class = {
            'running': 'label-success',
            'stopped': 'label-danger',
            'disabled': 'label-default',
            'unknown': 'label-default'
        };

        /* The one driver the design names as unable to read a key: it lights the screen and that
           is all it can do. Saying so beside the keypad switch is the difference between an
           honest page and one that leaves somebody pressing buttons at an appliance for an hour. */
        const no_key_drivers = ['mtc_s16209x'];

        /* ------------------------------------------------------------------ small helpers */

        /* Translatable text that lives in panels.json, not in this page: the name of
           each known appliance, the sentence saying how far its panel has actually been
           proven, and the notes beside it. lang._() resolves against a literal at compile
           time, so each one is listed as its own key - and fp_data_text is GENERATED, by
           tools/gen-data-strings.py, because a note added to panels.json and forgotten
           here comes out in English on an Arabic page with nothing to say so. */
        const fp_data_text = {
            'Sophos XG / XGS front panel': "{{ lang._('Sophos XG / XGS front panel') }}",
            'XG 330 rev 2 (smbios version 330r2), 2026-09-21: the display is verified - LCDd initialised the panel with no errors and the owner photographed live CPU, memory and uptime screens on it. The keypad is verified too: all four keys reported, measured one button at a time at ReportLevel 5 with the screen held still, three presses and three events each. The map above is that measurement and not LCDproc\'s default order, which puts Enter on 4,1 - where this panel has its down arrow.':
                "{{ lang._('XG 330 rev 2 (smbios version 330r2), 2026-09-21: the display is verified - LCDd initialised the panel with no errors and the owner photographed live CPU, memory and uptime screens on it. The keypad is verified too: all four keys reported, measured one button at a time at ReportLevel 5 with the screen held still, three presses and three events each. The map above is that measurement and not LCDproc\'s default order, which puts Enter on 4,1 - where this panel has its down arrow.') }}",
            'ConnectionType=ezio fixes the line at 2400 baud by itself - the driver reported \'serial: using speed: 2400\' with no Speed option set, so this entry deliberately does not write one.':
                "{{ lang._('ConnectionType=ezio fixes the line at 2400 baud by itself - the driver reported \'serial: using speed: 2400\' with no Speed option set, so this entry deliberately does not write one.') }}",
            'Heartbeat must stay off. This panel has no programmable character for LCDproc\'s heartbeat glyph and draws it as a solid black block in the corner.':
                "{{ lang._('Heartbeat must stay off. This panel has no programmable character for LCDproc\'s heartbeat glyph and draws it as a solid black block in the corner.') }}",
            'DelayMult=2 is what the owner settled on after trying 4: faster, and with RefreshDisplay redrawing the whole screen every few seconds it has not dropped a character.':
                "{{ lang._('DelayMult=2 is what the owner settled on after trying 4: faster, and with RefreshDisplay redrawing the whole screen every few seconds it has not dropped a character.') }}",
            'The panel is printed with a down arrow, ESC, an up arrow and ENTER, in that order, and that is the order of the matrix positions above.':
                "{{ lang._('The panel is printed with a down arrow, ESC, an up arrow and ENTER, in that order, and that is the order of the matrix positions above.') }}",
            'At 2400 baud the display and the keypad share the line: with screens changing every 3 seconds and a full redraw every 4, two thirds of the presses were lost. A quiet screen is what makes this keypad reliable: hold the screen still while measuring the keys, and keep the redraw interval wide on a panel whose keys are used.':
                "{{ lang._('At 2400 baud the display and the keypad share the line: with screens changing every 3 seconds and a full redraw every 4, two thirds of the presses were lost. A quiet screen is what makes this keypad reliable: hold the screen still while measuring the keys, and keep the redraw interval wide on a panel whose keys are used.') }}",
            'Sophos XGS front panel (the XGS 3300: SMBIOS XGS, board 17 / system 3300r1)':
                "{{ lang._('Sophos XGS front panel (the XGS 3300: SMBIOS XGS, board 17 / system 3300r1)') }}",
            'XGS 3300 (smbios XGS, version 17), 2026-10-02: the display is verified at 9600 - LCDd with hd44780, ConnectionType=ezio and Speed=9600 drew two lines of text the owner read on the panel as correct. The keys were measured on 2026-10-17: the owner pressed Enter, Esc, up and down in turn and the bridge sent A, B, C and D, one byte per press, without being asked. Size: 20 columns by 2 lines - the owner set 20x2 on the settings page on 2026-10-13 and the panel paints it, and the GIFAR bridge on this board drives a 20x2 HD44780 (os-xgs-npu\'s hardware page); the entry had said 16x2, the XG 330\'s size, until then.':
                "{{ lang._('XGS 3300 (smbios XGS, version 17), 2026-10-02: the display is verified at 9600 - LCDd with hd44780, ConnectionType=ezio and Speed=9600 drew two lines of text the owner read on the panel as correct. The keys were measured on 2026-10-17: the owner pressed Enter, Esc, up and down in turn and the bridge sent A, B, C and D, one byte per press, without being asked. Size: 20 columns by 2 lines - the owner set 20x2 on the settings page on 2026-10-13 and the panel paints it, and the GIFAR bridge on this board drives a 20x2 HD44780 (os-xgs-npu\'s hardware page); the entry had said 16x2, the XG 330\'s size, until then.') }}",
            'Speed=9600 is required. ConnectionType=ezio on its own fixes the line at 2400, which is right for the XG 330 rev 2 and wrong here: at 2400 this panel draws scattered x-with-a-bar characters - HD44780 code 0xF8 - which is the signature of bytes arriving at a quarter of the receiver\'s rate. A long start bit fills the low three bits with zeros and the next long bit fills the rest with ones.':
                "{{ lang._('Speed=9600 is required. ConnectionType=ezio on its own fixes the line at 2400, which is right for the XG 330 rev 2 and wrong here: at 2400 this panel draws scattered x-with-a-bar characters - HD44780 code 0xF8 - which is the signature of bytes arriving at a quarter of the receiver\'s rate. A long start bit fills the low three bits with zeros and the next long bit fills the rest with ones.') }}",
            'The vendor\'s own daemon sets the port with `stty ispeed 2400`. That sets only the INPUT speed, and a 16550-class UART has a single divisor, so on the vendor\'s system the line stays at the 9600 default. Reading the vendor\'s line setting literally is what kept this panel garbled for a week.':
                "{{ lang._('The vendor\'s own daemon sets the port with `stty ispeed 2400`. That sets only the INPUT speed, and a 16550-class UART has a single divisor, so on the vendor\'s system the line stays at the 9600 default. Reading the vendor\'s line setting literally is what kept this panel garbled for a week.') }}",
            'A rate sweep that sets the speed on the .init device and then writes through a fresh open of the port is not a reliable way to test this - that method is how every candidate rate once looked wrong. LCDd opens the port once and sets it with tcsetattr, which is why the decisive test was LCDd itself with Speed set.':
                "{{ lang._('A rate sweep that sets the speed on the .init device and then writes through a fresh open of the port is not a reliable way to test this - that method is how every candidate rate once looked wrong. LCDd opens the port once and sets it with tcsetattr, which is why the decisive test was LCDd itself with Speed set.') }}",
            'Heartbeat stays off, as on the XG 330: the panel has no programmable character for it.':
                "{{ lang._('Heartbeat stays off, as on the XG 330: the panel has no programmable character for it.') }}",
            'The keys are not read by LCDd here. The bridge never answers LCDd\'s key request (FE 06) and sends a letter of its own accord instead, which LCDd would discard - so LCDd is told Keypad=no and the plugin reads the port itself.':
                "{{ lang._('The keys are not read by LCDd here. The bridge never answers LCDd\'s key request (FE 06) and sends a letter of its own accord instead, which LCDd would discard - so LCDd is told Keypad=no and the plugin reads the port itself.') }}",
            'The panel is not drawn by LCDd either. Its bridge carries out no positioning command at all - clear, home and the line addresses are swallowed and do nothing - and writes every character at a cursor that runs round all forty cells, the first row and then the second. LCDd rewrites only what changed, so each update moved the whole picture by however many characters it wrote. The plugin draws this panel itself, always forty characters at once, which leaves the cursor where it was; the owner lines the text up once from the Buttons tab.':
                "{{ lang._('The panel is not drawn by LCDd either. Its bridge carries out no positioning command at all - clear, home and the line addresses are swallowed and do nothing - and writes every character at a cursor that runs round all forty cells, the first row and then the second. LCDd rewrites only what changed, so each update moved the whole picture by however many characters it wrote. The plugin draws this panel itself, always forty characters at once, which leaves the cursor where it was; the owner lines the text up once from the Buttons tab.') }}",
            'Sophos XG / XGS (panel not confirmed on this model)':
                "{{ lang._('Sophos XG / XGS (panel not confirmed on this model)') }}",
            'Nobody has confirmed this model yet. Press Test after applying: if the panel stays dark, try the driver list - mtc_s16209x lights a screen of this shape and cannot read a button, which is the honest fallback. The key map is copied from the XG 330 rev 2 and is a guess here: measure it with the key test before you trust which button is which.':
                "{{ lang._('Nobody has confirmed this model yet. Press Test after applying: if the panel stays dark, try the driver list - mtc_s16209x lights a screen of this shape and cannot read a button, which is the honest fallback. The key map is copied from the XG 330 rev 2 and is a guess here: measure it with the key test before you trust which button is which.') }}",
            'unrecognised appliance': "{{ lang._('unrecognised appliance') }}",
            'No proposal for this machine. Choose a driver and a serial port by hand - the page lists the drivers this installation of LCDproc actually carries and the ports this machine actually has - then press Test. Sending a report of what worked is how this table grows.':
                "{{ lang._('No proposal for this machine. Choose a driver and a serial port by hand - the page lists the drivers this installation of LCDproc actually carries and the ports this machine actually has - then press Test. Sending a report of what worked is how this table grows.') }}"
        };

        /* Volt escapes what lang._() returns, so an apostrophe inside a translated string arrives
           here as &#039;, and the API escapes every string it returns the same way. Both are read
           back to plain text before .text() is handed them, or the entity is what gets shown. */
        function plain(value) {
            return $('<textarea/>').html(value === null || value === undefined ? '' : String(value)).text();
        }

        function fp_data(value) {
            if (!value) { return ''; }
            return plain(fp_data_text[value] || value);
        }

        function esc(value) {
            return $('<div/>').text(value === null || value === undefined ? '' : value).html();
        }

        function is_object(value) {
            return value !== null && typeof value === 'object' && !$.isArray(value);
        }

        function close_button() {
            return {
                label: "{{ lang._('Close') }}",
                action: function (dialog) {
                    dialog.close();
                }
            };
        }

        function show_message(type, title, message) {
            BootstrapDialog.show({
                type: type,
                title: title,
                message: message,
                buttons: [close_button()]
            });
        }

        /* The API answers a refusal with `detail` and the script behind it with `message`. Take
           whichever arrived, because which one does depends on how far the request got. */
        function failure_text(data) {
            const detail = data ? (data.detail || data.message) : null;
            return detail ? '<br/><br/>' + esc(detail) : '';
        }

        function format_time(epoch) {
            const seconds = Number(epoch);
            if (!isFinite(seconds) || seconds <= 0) {
                return '';
            }
            const when = new Date(seconds * 1000);
            return isNaN(when.getTime()) ? '' : when.toLocaleString();
        }

        /* A count folded into a sentence, and written after a colon rather than in front of a
           noun. There is no plural form to reach from a page template, and "1 characters" is the
           kind of small wrongness that makes a careful page look careless in every language at
           once. */
        function counted(template, value) {
            return template.replace('{count}', String(value));
        }

        function label(text, classname) {
            return $('<span/>').addClass('label ' + classname).text(text);
        }

        function note(text, classname) {
            return $('<div/>').addClass('fp-note ' + (classname || '')).text(plain(text));
        }

        /* The long explanations sit under "full help", as they do on the settings tab: one switch
           on each of the other two tabs, both showing the same state, and a note drawn after the
           switch was turned is drawn in the state it was turned to. */
        let help_on = false;

        function help_note(text) {
            return $('<div class="help-block fp-help"/>').text(plain(text)).toggle(help_on);
        }

        $('.fp-help-toggle').click(function (event) {
            event.preventDefault();
            help_on = !help_on;
            $('.fp-help-toggle > i')
                .toggleClass('fa-toggle-on text-success', help_on)
                .toggleClass('fa-toggle-off text-danger', !help_on);
            $('.fp-help').toggle(help_on);
        });

        /* one row of a diagnostics section: what is read on the left, the reading on the right */
        function row(title, $value) {
            return $('<tr/>').append($('<td/>').text(title)).append($('<td/>').append($value));
        }

        function wide_row($content) {
            return $('<tr/>').append($('<td colspan="2"/>').append($content));
        }

        /* ------------------------------------------------------------------ the display */

        /* "16x2" as the panel is built: columns first, rows second. Anything that is not that
           shape is not a size, and the caller falls back rather than guessing a width - drawing a
           preview at a width nobody asked for would be worse than drawing none. */
        function parse_size(text) {
            const match = /^([1-9][0-9]{0,2})x([1-9][0-9]?)$/.exec(String(text || '').trim());
            if (match === null) {
                return null;
            }
            return {columns: parseInt(match[1], 10), rows: parseInt(match[2], 10)};
        }

        function form_size() {
            return parse_size($('#frontpanel\\.general\\.size').val());
        }

        /* The geometry the preview was drawn at, which comes from the firewall: it read the saved
           settings, so it is the truth about the panel rather than whatever is in the box on the
           settings tab at this second. Those two differ exactly while somebody is typing a new
           size and has not saved it, and the preview says so rather than quietly redrawing. The
           two numbers arrive as the width and the height of the display, which is the same pair
           as its columns and its rows; both spellings are read. */
        function preview_size() {
            if (preview_doc !== null) {
                const columns = Number(preview_doc.width !== undefined ? preview_doc.width : preview_doc.columns);
                const rows = Number(preview_doc.height !== undefined ? preview_doc.height : preview_doc.rows);
                if (isFinite(columns) && columns > 0 && isFinite(rows) && rows > 0) {
                    return {columns: Math.round(columns), rows: Math.round(rows)};
                }
            }
            return form_size();
        }

        /* A character a plain character panel can be expected to have a glyph for. The screen
           generator already folds what it cannot draw, so this rarely finds anything - and when
           it does, marking it is better than letting a row of question marks look deliberate. */
        function plain_character(character) {
            const code = character.codePointAt(0);
            return code >= 0x20 && code <= 0x7e;
        }

        function cell(character, cut) {
            const $cell = $('<span class="fp-cell"/>');
            /* a space still has to occupy its column, or the grid stops being a grid */
            $cell.text(character === ' ' ? ' ' : character);
            if (cut) {
                $cell.addClass('fp-cell-cut');
            }
            if (character !== ' ' && !plain_character(character)) {
                /* the colour comes from the theme's own warning class rather than from a value
                   written here, so the marking follows a theme into the dark */
                $cell.addClass('fp-cell-odd text-warning');
            }
            return $cell;
        }

        /* One row of the panel, cut where the panel cuts it.
           Everything past the last column is still drawn, dimmed and struck through behind a
           marker, because the whole reason this preview exists is to show somebody the part of
           their line that never arrives. Counted in code points rather than in bytes: a panel
           counts cells. */
        function draw_row(text, columns) {
            const $row = $('<div class="fp-lcd-row"/>');
            const characters = Array.from(text === null || text === undefined ? '' : String(text));
            for (let index = 0; index < columns; index++) {
                $row.append(cell(index < characters.length ? characters[index] : ' ', false));
            }
            if (characters.length > columns) {
                $row.append($('<span class="fp-lcd-edge"/>'));
                for (let index = columns; index < characters.length; index++) {
                    $row.append(cell(characters[index], true));
                }
            }
            return $row;
        }

        /* Everything the preview has to say about one screen, over and above its two rows: how
           much of it the panel will drop, what the owner typed where the panel could not draw it,
           and why a screen is not being shown at all. */
        function screen_notes(entry, geometry) {
            const notes = [];
            const lines = $.isArray(entry.lines) ? entry.lines : [];
            let cut = 0;
            let odd = 0;

            lines.forEach(function (line) {
                const characters = Array.from(String(line === null || line === undefined ? '' : line));
                if (characters.length > geometry.columns) {
                    cut += characters.length - geometry.columns;
                }
                characters.forEach(function (character) {
                    if (character !== ' ' && !plain_character(character)) {
                        odd += 1;
                    }
                });
            });

            if (cut > 0) {
                notes.push({
                    type: 'warning',
                    text: counted(
                        "{{ lang._('Longer than the display. Characters that never reach the panel: {count}.') }}",
                        cut
                    )
                });
            }
            if (odd > 0) {
                notes.push({
                    type: 'warning',
                    text: counted(
                        "{{ lang._('Characters outside the plain ASCII range: {count}. A character panel draws whatever its own character table holds in that slot, which is rarely what was typed.') }}",
                        odd
                    )
                });
            }
            if (lines.length > geometry.rows) {
                notes.push({
                    type: 'warning',
                    text: "{{ lang._('This screen offers more lines than the panel has rows, so the last of them are never reached.') }}"
                });
            }
            /* `source` is what the owner typed, handed back only when folding it to what the
               panel can draw changed it. Showing both is the whole answer to "why does my
               message look like that". */
            if (entry.source) {
                notes.push({
                    type: 'warning',
                    text: "{{ lang._('The panel has no glyph for some of these characters, so they were folded to what it can draw. As typed:') }}" +
                        ' ' + String(entry.source)
                });
            } else if (entry.note) {
                notes.push({type: 'info', text: String(entry.note)});
            }
            /* why a screen has nothing to say - in the script's words, because only the script
               knows which file it went looking for */
            if (entry.reason) {
                notes.push({type: 'info', text: String(entry.reason)});
            }
            return notes;
        }

        function draw_screen(entry, geometry) {
            const key = String(entry.key || entry.kind || '');
            const shown = entry.enabled !== false;
            const available = entry.available !== false;
            const $panel = $('<div class="fp-screen"/>');

            const $heading = $('<div class="fp-screen-head"/>');
            $heading.append($('<span class="fp-screen-name"/>')
                .text(screen_title[key] || String(entry.title || key)));
            if (!shown) {
                $heading.append(' ').append(label("{{ lang._('not in the rotation') }}", 'label-default'));
            }
            if (!available) {
                $heading.append(' ').append(label("{{ lang._('nothing to show') }}", 'label-default'));
            }
            $panel.append($heading);

            if (available) {
                const lines = $.isArray(entry.lines) ? entry.lines : [];
                const $lcd = $('<div class="fp-lcd"/>');
                for (let row = 0; row < geometry.rows; row++) {
                    $lcd.append(draw_row(row < lines.length ? lines[row] : '', geometry.columns));
                }
                $panel.append($lcd);
            }

            screen_notes(entry, geometry).forEach(function (item) {
                $panel.append($('<div class="fp-screen-note"/>')
                    .addClass(item.type === 'warning' ? 'text-warning' : 'fp-muted')
                    .append($('<i class="fa fa-fw"/>').addClass(
                        item.type === 'warning' ? 'fa-exclamation-triangle' : 'fa-info-circle'
                    ))
                    .append(' ')
                    .append($('<span/>').text(item.text)));
            });

            return $panel;
        }

        /* ------------------------------------------------------------------ the preview */

        function draw_preview() {
            const $body = $('#preview-body').empty();
            const $summary = $('#preview-summary');

            if (preview_doc === null) {
                $summary.text("{{ lang._('The firewall did not answer with a preview.') }}");
                return;
            }
            if (preview_doc.status && preview_doc.status !== 'ok') {
                $summary.text("{{ lang._('The preview could not be drawn.') }}");
                $body.append($('<div class="alert alert-warning fp-alert" role="alert"/>')
                    .text(preview_doc.detail || preview_doc.message ||
                        "{{ lang._('The front panel script reported no reason.') }}"));
                return;
            }

            const geometry = preview_size();
            if (geometry === null) {
                $summary.text("{{ lang._('The size of the display is not set, so there is no width to draw at.') }}");
                return;
            }

            const screens = $.isArray(preview_doc.screens) ? preview_doc.screens : [];
            const shown = screens.filter(function (entry) {
                return entry.enabled !== false;
            });

            $summary.text(
                "{{ lang._('Screens in the rotation: {count}. Drawn at {columns} columns by {rows} rows.') }}"
                    .replace('{count}', String(shown.length))
                    .replace('{columns}', String(geometry.columns))
                    .replace('{rows}', String(geometry.rows))
            );

            /* A size typed into the box and not yet saved is a size the firewall has never heard
               of, and drawing at it would be a picture of a panel nobody has. */
            const typed = form_size();
            if (typed !== null && (typed.columns !== geometry.columns || typed.rows !== geometry.rows)) {
                $body.append($('<div class="alert alert-info fp-alert" role="alert"/>').text(
                    "{{ lang._('The settings tab has a different size in it. Save the settings to see the preview at that size.') }}"
                ));
            }

            if (screens.length === 0) {
                $body.append($('<div class="alert alert-info fp-alert" role="alert"/>').text(
                    "{{ lang._('The firewall listed no screens at all.') }}"
                ));
                return;
            }
            if (shown.length === 0) {
                $body.append($('<div class="alert alert-warning fp-alert" role="alert"/>').text(
                    "{{ lang._('Nothing is in the rotation, so the panel has nothing of ours to show.') }}"
                ));
            }

            screens.forEach(function (entry) {
                $body.append(draw_screen(entry, geometry));
            });
        }

        function reload_preview(done) {
            ajaxGet('/api/frontpanel/service/preview', {}, function (data) {
                preview_doc = is_object(data) ? data : null;
                draw_cards();
                draw_preview();
                update_rotation_note();
                if (!bt_selected) {
                    /* the drawn panel shows what the real one is showing */
                    bt_lcd_idle();
                }
                if (typeof done === 'function') {
                    done();
                }
            });
        }

        /* The settings tab is where somebody turns the panel on, and the answer to "why is the
           screen blank" lives as often in the rotation as in the settings above it. */
        function update_rotation_note() {
            const $note = $('#rotation-note').empty();
            if (preview_doc === null || !$.isArray(preview_doc.screens)) {
                return;
            }
            const shown = preview_doc.screens.filter(function (entry) {
                return entry.enabled !== false && entry.available !== false;
            });
            if (shown.length > 0) {
                return;
            }
            $note.append($('<div class="alert alert-warning fp-alert" role="alert"/>')
                .append($('<i class="fa fa-fw fa-exclamation-triangle"/>'))
                .append(' ')
                .append($('<span/>').text(
                    "{{ lang._('No screen in the rotation has anything to show, so the panel would stay as it is. The preview tab says which screens were skipped and why.') }}"
                )));
        }

        /* ------------------------------------------------------------------ diagnostics */

        /* The diagnostics answer carries two reports that were written separately: what the keys
           have done, and what this machine looks like from the outside. Each is read from under
           its own name where the firewall nests it, and from the answer itself where the firewall
           hands the two back merged - the fields do not collide, so both shapes can be read
           without ever guessing which one arrived. */
        function keys_report() {
            if (diagnostics_doc === null) {
                return null;
            }
            return is_object(diagnostics_doc.keys) ? diagnostics_doc.keys : diagnostics_doc;
        }

        function panel_report() {
            if (diagnostics_doc === null) {
                return null;
            }
            return is_object(diagnostics_doc.panels) ? diagnostics_doc.panels : diagnostics_doc;
        }

        /* Summary cards above the tabs, as on the coprocessor's pages: the service, the panel as it
           is set, the screens in the rotation and the keys - each redrawn when what it reads
           changes, and blank until it has been read. */
        let service_status = null;

        function card(cls, icon, key, value, sub) {
            return $('<div class="fp-card"/>').addClass(cls)
                .append($('<i class="fa"/>').addClass(icon))
                .append($('<div class="k"/>').text(key))
                .append($('<div class="v"/>').text(value))
                .append($('<div class="s"/>').text(sub || ' '));
        }

        function draw_cards() {
            const tone = {'running': 'ok', 'stopped': 'bad', 'disabled': '', 'unknown': 'warn'};
            const state = String(service_status || 'unknown');
            const driver = String($('#frontpanel\\.general\\.driver').val() || '');
            const size = String($('#frontpanel\\.general\\.size').val() || '');
            const device = String($('#frontpanel\\.general\\.device').val() || '');
            const screens = (preview_doc !== null && $.isArray(preview_doc.screens)) ? preview_doc.screens : null;
            const shown = screens === null ? null : screens.filter(function (entry) {
                return entry.enabled !== false && entry.available !== false;
            }).length;
            const keypad = $('#frontpanel\\.general\\.keypad').is(':checked');
            $('#fp-cards').empty()
                .append(card(service_status === null ? '' : (tone[state] || ''), 'fa-power-off', "{{ lang._('Service') }}",
                    service_status === null ? '…' : (service_text[state] || service_text.unknown), ''))
                .append(card(driver ? 'ok' : 'warn', 'fa-desktop', "{{ lang._('Panel') }}",
                    [driver, size].filter(Boolean).join(' ') || '…', device))
                .append(card(shown ? 'ok' : (shown === 0 ? 'warn' : ''), 'fa-th-list', "{{ lang._('Screens') }}",
                    shown === null ? '…' : String(shown), "{{ lang._('in the rotation, with something to show') }}"))
                .append(card(keypad ? 'ok' : '', 'fa-keyboard-o', "{{ lang._('Keys') }}",
                    keypad ? "{{ lang._('read') }}" : "{{ lang._('not read') }}", "{{ lang._('the buttons beside the screen') }}"));
        }

        function draw_service_state(status) {
            service_status = status || 'unknown';
            draw_cards();
            const state = String(status || 'unknown');
            const $line = $('#service-state').empty();
            $line.append(label(service_text[state] || service_text.unknown,
                service_class[state] || service_class.unknown));
            const sentence = {
                'running': "{{ lang._('The screen client and LCDproc are both up, and the panel is being written to.') }}",
                'stopped': "{{ lang._('The panel is enabled but the service is not running. Its log under System will say why.') }}",
                'disabled': "{{ lang._('The panel is turned off, so nothing is being written to it.') }}",
                'unknown': "{{ lang._('The service did not say whether it is running.') }}"
            }[state] || '';
            $line.append(' ').append($('<span class="fp-sub"/>').text(sentence));
        }

        function reload_service_state() {
            ajaxGet('/api/frontpanel/service/status', {}, function (data) {
                draw_service_state(data ? data.status : null);
            });
        }

        function draw_keys() {
            const $body = $('#keys-body').empty();
            const report = keys_report();
            /* Called from two places - the diagnostics answer and the driver box - and the second
               of them can easily arrive first. Saying "no key has been reported" before anybody
               has been asked would be a lie with a short shelf life, but a lie. */
            if (report === null) {
                $body.append(note("{{ lang._('Asking the firewall...') }}"));
                return;
            }

            const driver = String($('#frontpanel\\.general\\.driver').val() || '');
            if ($.inArray(driver, no_key_drivers) !== -1) {
                $body.append(note(
                    "{{ lang._('This driver lights the screen and cannot read a key at all. The rotation runs on its timer, which is all it ever needed.') }}"
                ));
                return;
            }
            if (report.keypad !== true) {
                $body.append(note(
                    "{{ lang._('The keys are not being polled. Turn on Read the keys in the settings to find out whether this panel answers.') }}"
                ));
                return;
            }

            const seen = $.isArray(report.keys) ? report.keys : [];
            if (seen.length === 0) {
                $body.append(note("{{ lang._('No key has been reported yet.') }}"));
                $body.append(help_note(
                    "{{ lang._('The keys are polled rather than volunteered, so silence here means the panel answered the poll with nothing - press one and look again. If nothing ever arrives, this panel may simply be unable to report a key, which is a limit of the hardware and not a fault.') }}"
                ));
            } else {
                const $table = $('<table class="table table-condensed fp-keys"/>');
                const $head = $('<tr/>');
                [
                    "{{ lang._('Key') }}",
                    "{{ lang._('Where on the keypad') }}",
                    "{{ lang._('In the log') }}",
                    "{{ lang._('At the screen client') }}"
                ].forEach(function (title) {
                    $head.append($('<th/>').text(title));
                });
                $table.append($('<thead/>').append($head));

                const $rows = $('<tbody/>');
                seen.forEach(function (entry) {
                    const $row = $('<tr/>');
                    $row.append($('<td/>').append($('<span class="fp-tech fp-strong"/>').text(String(entry.name || ''))));
                    $row.append($('<td/>').append($('<span class="fp-tech"/>').text(String(entry.matrix || ''))));
                    $row.append($('<td/>').append($('<span class="fp-tech"/>').text(String(entry.log || 0))));
                    $row.append($('<td/>').append($('<span class="fp-tech"/>').text(String(entry.client || 0))));
                    $rows.append($row);
                });
                $table.append($rows);
                $body.append($table);

                const recent = $.isArray(report.recent) ? report.recent.slice().reverse() : [];
                if (recent.length > 0) {
                    $body.append($('<div class="fp-label fp-strong"/>').text("{{ lang._('The last presses to arrive') }}"));
                    const $list = $('<ul class="fp-presses"/>');
                    recent.forEach(function (press) {
                        $list.append($('<li/>')
                            .append($('<span class="fp-tech fp-strong"/>').text(String(press.key || '')))
                            .append(' ')
                            .append($('<span class="fp-tech fp-muted"/>').text(format_time(press.at))));
                    });
                    $body.append($list);
                }
            }

            /* A log that would not name a key even if one arrived. The numbers are LCDproc's, so
               the sentence is built here rather than repeated from the script: it is the same
               fact said where gettext can reach it. */
            const log = is_object(report.log) ? report.log : null;
            const covered = log !== null && log.report_level !== null && log.report_level !== undefined &&
                log.reports_keys === false;
            if (covered) {
                $body.append(help_note(
                    "{{ lang._('LCDproc is writing its log at level {level}, and it names a key only at level {needed} or higher. What is shown here came from the screen client, which is the stronger evidence anyway.') }}"
                        .replace('{level}', String(log.report_level))
                        .replace('{needed}', String(KEY_REPORT_LEVEL))
                ));
            }

            /* Anything else the firewall wanted to say about the keys that this page has no
               sentence of its own for. Shown as the script wrote it rather than dropped. */
            if (report.note && seen.length > 0 && !covered) {
                $body.append(help_note(String(report.note)));
            }
        }

        function draw_devices() {
            const report = panel_report();
            const $body = $('#devices-body').empty();
            /* Same caution as the keys panel: this is drawn again whenever the driver box
               changes, and that can happen before the firewall has been asked anything. "No
               serial port" is a serious thing to tell somebody, and it must not be said on the
               strength of not having looked. */
            if (report === null) {
                $body.append(wide_row(note("{{ lang._('Asking the firewall...') }}")));
                return;
            }
            const entries = $.isArray(report.devices) ? report.devices : [];
            /* Written either as a list of device nodes or as a list of what is known about each
               one. Both are read, because a plain name is all this list needs to be useful. */
            const devices = entries.map(function (entry) {
                return is_object(entry) ? String(entry.device || '') : String(entry);
            }).filter(function (device) {
                return device !== '';
            });

            if (devices.length === 0) {
                $body.append(wide_row(note(
                    "{{ lang._('This machine reports no serial port. A panel on a port that is not there cannot be written to.') }}"
                )));
            } else {
                entries.forEach(function (entry) {
                    const device = is_object(entry) ? String(entry.device || '') : String(entry);
                    if (device === '') {
                        return;
                    }
                    const $item = $('<div/>');
                    /* A port with a login prompt on it is a port this plugin must not claim: the
                       two would write over each other, and the one that loses is whoever was
                       using the console. */
                    if (!(is_object(entry) && entry.getty)) {
                        $item.append($('<span class="fp-muted"/>').text("{{ lang._('no login prompt configured') }}"));
                    } else {
                        $item.append(label("{{ lang._('a login prompt is configured here') }}", 'label-warning'));
                        /* What the firewall read about the port, not a sentence about it: the
                           name /etc/ttys knows it by, the command on that line, the flags beside
                           it and the line itself. The line is the part worth showing, because it
                           is what the owner will find when they open the file - and handing the
                           whole report to text() would put [object Object] under a serial port,
                           which is the least useful thing a diagnostics page can say. A firewall
                           that sent a plain string instead is printed as it arrived. */
                        const ttys = is_object(entry.ttys) ? entry.ttys : null;
                        const line = ttys !== null ? String(ttys.line || '') : String(entry.ttys || '');
                        if (line !== '') {
                            $item.append($('<div class="fp-note fp-tech"/>').text(line));
                        }
                    }
                    $body.append($('<tr/>')
                        .append($('<td/>').append($('<span class="fp-tech fp-strong"/>').text(device)))
                        .append($('<td/>').append($item)));
                });
            }

            /* Which of the 36 names in the driver list this installation actually carries. The
               model offers them all, because the list is the same on every installation of the
               same package - but if this one is missing the chosen driver, LCDd will fail to
               start and say so in a log nobody has opened yet. */
            const installed = $.isArray(report.drivers) ? report.drivers : [];
            const driver = String($('#frontpanel\\.general\\.driver').val() || '');
            if (installed.length > 0 && driver !== '' && $.inArray(driver, installed) === -1) {
                $body.append(wide_row(note(
                    "{{ lang._('The chosen driver is not among the drivers installed on this firewall, so LCDproc will refuse to start.') }}",
                    'text-warning'
                )));
            }

            draw_device_choices(devices);
        }

        /* The ports this machine has, offered beside the box on the settings tab rather than
           baked into the model: a machine gains a serial port the moment somebody plugs in a USB
           adapter, and a list fixed at install time would refuse the port that appeared after it.
           The box stays a box, so an unusual name can still be typed into it. */
        function draw_device_choices(devices) {
            const signature = devices.join(' ');
            if (signature === devices_drawn) {
                return;
            }
            devices_drawn = signature;

            const $input = $('#frontpanel\\.general\\.device');
            if ($input.length === 0) {
                return;
            }
            $('#fp-device-choices').remove();
            $('#fp-device-list').remove();
            if (devices.length === 0) {
                return;
            }

            /* typed into, the box offers the same list the browser's own way */
            const $datalist = $('<datalist id="fp-device-list"/>');
            devices.forEach(function (device) {
                $datalist.append($('<option/>').attr('value', device));
            });
            $input.attr('list', 'fp-device-list');

            const $choices = $('<div id="fp-device-choices" class="fp-note"/>');
            $choices.append($('<span/>').text("{{ lang._('This machine has:') }}")).append(' ');
            devices.forEach(function (device) {
                $choices.append($('<button type="button" class="btn btn-xs btn-default fp-port-pick"/>')
                    .append($('<span class="fp-tech"/>').text(device)));
            });
            $input.parent().append($datalist).append($choices);
        }

        /* What the shipped table of known appliances proposes for this machine. Nothing is ever
           applied on its own initiative: a wrong driver writing to the wrong serial port is not a
           mistake a plugin should make for somebody, so this fills the boxes and stops, and the
           owner reads them and presses Save. Where the firewall proposes nothing, the panel
           disappears and nothing else on the page changes. */
        function draw_suggestion() {
            const report = panel_report();
            const $body = $('#suggestion-body').empty();
            const panel = (report !== null && is_object(report.panel)) ? report.panel : null;
            const matched = panel !== null && (report.matched === true || !!panel.driver);
            $('.fp-suggestion').toggle(panel !== null && (matched || !!panel.hint));
            if (panel === null) {
                return;
            }

            if (matched) {
                /* What the table itself admits to, printed as it was written. An entry says what
                   has been confirmed and by whom, and a proposal read without that line is a
                   guess read as a fact - so an unconfirmed one says so in plain sight, and the
                   long account of a confirmed one waits under full help. */
                const $entry = $('<div/>').append($('<span class="fp-strong"/>').text(
                    fp_data(String(panel.display || report.match || ''))));
                if (panel.confirmed) {
                    $entry.append(help_note(fp_data(String(panel.confirmed))));
                } else {
                    $entry.append(note(
                        "{{ lang._('Nobody has confirmed this proposal on this model yet. It is where to start, not what to expect.') }}",
                        'text-warning'
                    ));
                }
                $body.append(row("{{ lang._('Matched entry') }}", $entry));

                const options = is_object(panel.options) ? panel.options : {};
                [
                    ["{{ lang._('Driver') }}", panel.driver],
                    ["{{ lang._('Connection type') }}", options.ConnectionType],
                    ["{{ lang._('Serial port') }}", options.Device],
                    ["{{ lang._('Size') }}", options.Size]
                ].forEach(function (pair) {
                    if (pair[1] === undefined || pair[1] === null || pair[1] === '') {
                        return;
                    }
                    $body.append(row(pair[0], $('<span class="fp-tech"/>').text(String(pair[1]))));
                });

                $body.append(row('', $('<div/>')
                    .append($('<button type="button" id="applySuggestionAct" class="btn btn-default btn-xs"/>')
                        .text("{{ lang._('Put these in the settings') }}"))
                    .append(help_note(
                        "{{ lang._('This only fills the boxes on the settings tab. Nothing reaches the panel until they are saved.') }}"
                    ))));
            }

            if (panel.hint) {
                $body.append(wide_row(note(fp_data(String(panel.hint)))));
            }
        }

        function reload_diagnostics(done) {
            ajaxGet('/api/frontpanel/service/diagnostics', {}, function (data) {
                diagnostics_doc = is_object(data) ? data : null;
                draw_keys();
                draw_devices();
                draw_suggestion();
                if (typeof done === 'function') {
                    done();
                }
            });
            reload_service_state();
        }

        $('#suggestion-body').on('click', '#applySuggestionAct', function () {
            const report = panel_report();
            const panel = (report !== null && is_object(report.panel)) ? report.panel : null;
            if (panel === null) {
                return;
            }
            const options = is_object(panel.options) ? panel.options : {};
            if (panel.driver) {
                $('#frontpanel\\.general\\.driver').val(String(panel.driver));
            }
            if (options.ConnectionType) {
                $('#frontpanel\\.general\\.connection').val(String(options.ConnectionType));
            }
            if (options.Device) {
                $('#frontpanel\\.general\\.device').val(String(options.Device));
            }
            if (options.Size) {
                $('#frontpanel\\.general\\.size').val(String(options.Size));
            }
            /* the table writes the keypad the way LCDd.conf writes it */
            if (options.Keypad !== undefined) {
                $('#frontpanel\\.general\\.keypad').prop('checked', String(options.Keypad) === 'yes');
            }
            $('.selectpicker').selectpicker('refresh');
            driver_changed();
            $('a[href="#settings"]').tab('show');
            show_message(BootstrapDialog.TYPE_INFO, "{{ lang._('Front Panel') }}",
                "{{ lang._('The settings have been filled in from the table. Read them, then save to apply them.') }}");
        });

        /* ------------------------------------------------------------------ the test line */

        $('#testAct').click(function () {
            const $button = $(this);
            const $icon = $button.find('i');
            $button.prop('disabled', true);
            $icon.removeClass('fa-paper-plane').addClass('fa-spinner fa-pulse');
            ajaxCall('/api/frontpanel/service/test', {'text': $('#test-text').val()}, function (data) {
                $button.prop('disabled', false);
                $icon.removeClass('fa-spinner fa-pulse').addClass('fa-paper-plane');
                const ok = data && data.status === 'ok';
                show_message(
                    ok ? BootstrapDialog.TYPE_SUCCESS : BootstrapDialog.TYPE_WARNING,
                    "{{ lang._('Front panel test') }}",
                    ok
                        ? "{{ lang._('The line was sent. Look at the panel: it holds the line for a moment and then gives the panel back to the rotation.') }}" + failure_text(data)
                        : "{{ lang._('The line was not sent.') }}" + failure_text(data)
                );
                reload_service_state();
            });
        });

        /* ------------------------------------------------------------------ settings */

        /* The keypad switch is worth an honest word beside it the moment a driver that cannot
           read a key is chosen, rather than after the appliance has been pressed at for an hour. */
        function driver_changed() {
            const driver = String($('#frontpanel\\.general\\.driver').val() || '');
            const $note = $('#keypad-note').empty();
            if ($.inArray(driver, no_key_drivers) !== -1) {
                $note.text("{{ lang._('The chosen driver lights the screen and cannot read a key, so this switch will make no difference.') }}");
            }
            draw_keys();
            draw_devices();
        }

        /* The rotation arrives as the list that was saved, in the order it was saved, and that is
           all it arrives as - a stored list knows nothing of the screens nobody chose. So the
           screens that are not in it are added here as choices, and every entry is given the name
           this page calls it by, before the tokeniser turns the lot into draggable tokens. Order
           is the point: the tokeniser keeps the select in the order of its tokens, and that order
           is what gets saved. */
        function prepare_rotation() {
            const $select = $('#frontpanel\\.general\\.screens');
            if ($select.length === 0) {
                return;
            }
            $select.find('option').each(function () {
                const key = $(this).val();
                if (screen_title[key] !== undefined) {
                    $(this).text(screen_title[key]);
                }
            });
            Object.keys(screen_title).forEach(function (key) {
                if ($select.find('option').filter(function () { return $(this).val() === key; }).length === 0) {
                    $select.append($('<option/>').attr('value', key).text(screen_title[key]));
                }
            });
        }

        const data_get_map = {'frm_general': '/api/frontpanel/settings/get'};
        mapDataToFormUI(data_get_map).done(function () {
            draw_cards();
            /* the choices have to be in the select before the tokeniser reads it, or the list it
               offers is only the screens that were already chosen */
            prepare_rotation();
            formatTokenizersUI();
            $('.selectpicker').selectpicker('refresh');
            /* the note under the keypad switch has to exist before anything can be written into
               it, and it belongs in the same cell as the switch */
            $('#frontpanel\\.general\\.keypad').parent().append($('<div id="keypad-note" class="fp-note text-warning"/>'));
            $('#frontpanel\\.general\\.driver').change(driver_changed);
            driver_changed();
            /* the ports may well have arrived before the form did */
            devices_drawn = '';
            draw_devices();
        });

        $('#settings').on('click', '.fp-port-pick', function () {
            $('#frontpanel\\.general\\.device').val($(this).text().trim());
        });

        /* Saving is only half of it. LCDd reads its configuration once, when it starts, so a
           speed written into the file and not applied is a speed nobody is running at - which is
           exactly the confusion this button exists to avoid. */
        $('#saveAct').click(function () {
            const $button = $(this);
            const $progress = $('#frm_general_progress');
            $button.prop('disabled', true);
            $progress.addClass('fa fa-spinner fa-pulse');
            saveFormToEndpoint('/api/frontpanel/settings/set', 'frm_general', function () {
                apply_settings(function () {
                    $progress.removeClass('fa fa-spinner fa-pulse');
                    $button.prop('disabled', false);
                });
            }, false, function () {
                $progress.removeClass('fa fa-spinner fa-pulse');
                $button.prop('disabled', false);
            });
        });

        function apply_settings(done) {
            ajaxCall('/api/frontpanel/service/reconfigure', {}, function (data) {
                updateServiceControlUI('frontpanel');
                reload_service_state();
                reload_preview();
                reload_diagnostics();
                if (data && data.status !== 'ok') {
                    show_message(BootstrapDialog.TYPE_WARNING, "{{ lang._('Front Panel') }}",
                        "{{ lang._('The settings were saved, but the service did not take them.') }}" + failure_text(data));
                }
                if (typeof done === 'function') {
                    done();
                }
            });
        }

        /* ------------------------------------------------------------------ the buttons */

        /* The tab is a drawing of the panel. A key is chosen by clicking it there, by clicking its
           card, or by pressing it at the rack - the page watches the presses while the tab is open
           and lights up the one that arrived. Choosing what it does is one click on a tile, saved at
           once: the screen client looks at the settings every few seconds and follows them without
           a restart. The grid behind "Show as a table" is the same data, for keys the drawing does
           not know and for the codes. */
        const BT_PRESS_MS = 1500;
        const bt_actions = ['next', 'previous', 'menu', 'back', 'pause', 'screen', 'backlight', 'none'];
        const bt_action_text = {
            'next': "{{ lang._('Next screen') }}",
            'previous': "{{ lang._('Previous screen') }}",
            'menu': "{{ lang._('Open the menu') }}",
            'back': "{{ lang._('Back to the rotation') }}",
            'pause': "{{ lang._('Hold or resume the rotation') }}",
            'screen': "{{ lang._('Show one screen') }}",
            'backlight': "{{ lang._('Backlight on or off') }}",
            'none': "{{ lang._('Nothing') }}"
        };
        const bt_action_icon = {
            'next': 'fa-arrow-circle-down',
            'previous': 'fa-arrow-circle-up',
            'menu': 'fa-bars',
            'back': 'fa-undo',
            'pause': 'fa-pause-circle',
            'screen': 'fa-desktop',
            'backlight': 'fa-lightbulb-o',
            'none': 'fa-ban'
        };
        /* what is printed on the arrow keys, drawn rather than spelled */
        const bt_glyph = {'Up': '▲', 'Down': '▼', 'Left': '◀', 'Right': '▶'};

        let bt_defaults = [];       /* the keys this appliance has, in the panel's order */
        let bt_direct = false;      /* whether the plugin reads this panel's keys itself */
        let bt_ring = false;        /* whether the plugin draws this panel as a ring of cells */
        let bt_rows = {};           /* key name -> the owner's row, where there is one */
        let bt_selected = '';
        let bt_seen = null;         /* presses counted at the last look, null before the first */
        let bt_busy = false;

        function bt_option(field) {
            if (!is_object(field)) {
                return field === undefined || field === null ? '' : String(field);
            }
            let chosen = '';
            Object.keys(field).forEach(function (name) {
                if (Number(field[name].selected) === 1) {
                    chosen = name;
                }
            });
            return chosen;
        }

        function bt_default(key) {
            return bt_defaults.filter(function (row) { return row.key === key; })[0] || {'key': key};
        }

        function bt_keys() {
            const keys = bt_defaults.map(function (row) { return row.key; });
            Object.keys(bt_rows).sort().forEach(function (key) {
                if (keys.indexOf(key) < 0) {
                    keys.push(key);
                }
            });
            return keys;
        }

        /* what a key does now: the owner's row where it is on, the appliance's default otherwise */
        function bt_effective(key) {
            const row = bt_rows[key];
            const fallback = bt_default(key);
            const own = row && row.enabled;
            return {
                'own': !!own,
                'label': plain((row && row.label) || fallback.label || key),
                'code': (row && row.code) || fallback.code || '',
                'action': own ? row.action : (fallback.action || 'none'),
                'target': own ? row.target : ''
            };
        }

        function bt_face_label(key, label) {
            return bt_glyph[key] || label;
        }

        function bt_lcd(lines) {
            const $lines = $('#fp-face-lcd .fp-face-line');
            $lines.eq(0).text(lines[0] || '');
            $lines.eq(1).text(lines[1] || '');
        }

        function bt_lcd_idle() {
            const screens = (preview_doc !== null && $.isArray(preview_doc.screens)) ? preview_doc.screens : [];
            const first = screens.filter(function (entry) {
                return entry.enabled !== false && entry.available !== false && $.isArray(entry.lines);
            })[0];
            bt_lcd(first ? first.lines : ['', '']);
        }

        function bt_draw() {
            const keys = bt_keys();
            const $face = $('#fp-face-keys').empty();
            const $cards = $('#fp-bt-cards').empty();

            keys.forEach(function (key) {
                const now = bt_effective(key);
                $face.append($('<button type="button" class="fp-key"/>')
                    .attr('data-key', key)
                    .attr('title', now.label)
                    .toggleClass('selected', key === bt_selected)
                    .text(bt_face_label(key, now.label)));

                let tone = now.own ? 'ok' : '';
                if (bt_direct && !now.code) {
                    tone = 'warn';
                }
                const sub = [];
                if (now.action === 'screen' && now.target) {
                    sub.push(screen_title[now.target] || now.target);
                }
                sub.push(now.own ? "{{ lang._('set here') }}" : "{{ lang._('default') }}");
                if (bt_direct) {
                    sub.push(now.code ? "{{ lang._('code') }} " + now.code : "{{ lang._('no code yet') }}");
                }
                $cards.append(card(tone, bt_action_icon[now.action] || 'fa-circle-o', now.label,
                    plain(bt_action_text[now.action] || now.action), sub.map(plain).join(' · '))
                    .addClass('fp-bt-card')
                    .toggleClass('selected', key === bt_selected)
                    .attr('data-key', key)
                    .attr('role', 'button')
                    .attr('tabindex', '0'));
            });

            if (!keys.length) {
                $('#buttons-note').text(plain("{{ lang._('This appliance has no known keys. Show the table to add one by name.') }}"));
            }
            bt_draw_editor();
        }

        function bt_draw_editor() {
            const $editor = $('#fp-bt-editor');
            if (!bt_selected) {
                $editor.hide();
                bt_lcd_idle();
                return;
            }
            const now = bt_effective(bt_selected);
            $('#fp-bt-editing').text(plain("{{ lang._('What this key does:') }}") + ' ' + now.label);
            $('#fp-bt-reset').toggle(!!bt_rows[bt_selected]);

            const $actions = $('#fp-bt-actions').empty();
            bt_actions.forEach(function (action) {
                $actions.append($('<button type="button" class="fp-tile"/>')
                    .attr('data-action', action)
                    .toggleClass('active', action === now.action)
                    .append($('<i class="fa fa-fw"/>').addClass(bt_action_icon[action]))
                    .append($('<span/>').text(plain(bt_action_text[action]))));
            });

            const $screens = $('#fp-bt-screens').empty();
            Object.keys(screen_title).forEach(function (key) {
                $screens.append($('<button type="button" class="fp-tile fp-tile-small"/>')
                    .attr('data-target', key)
                    .toggleClass('active', now.action === 'screen' && now.target === key)
                    .text(plain(screen_title[key])));
            });
            $('#fp-bt-screens-wrap').toggle(now.action === 'screen' || $editor.data('picking') === true);

            bt_lcd([now.label, plain(bt_action_text[now.action] || now.action)]);
            $editor.show();
        }

        function bt_load(done) {
            ajaxGet('/api/frontpanel/service/buttons', {}, function (defaults) {
                bt_defaults = (defaults && $.isArray(defaults.buttons)) ? defaults.buttons : [];
                bt_direct = !!(defaults && defaults.direct);
                bt_ring = !!(defaults && defaults.ring);
                $('#fp-align').toggle(bt_ring);
                ajaxGet('/api/frontpanel/settings/get', {}, function (data) {
                    const grid = (((data || {}).frontpanel || {}).buttons || {}).button || {};
                    bt_rows = {};
                    Object.keys(is_object(grid) ? grid : {}).forEach(function (uuid) {
                        const row = grid[uuid];
                        bt_rows[String(row.key)] = {
                            'uuid': uuid,
                            'enabled': String(row.enabled) === '1',
                            'label': String(row.label || ''),
                            'code': String(row.code || ''),
                            'action': bt_option(row.action),
                            'target': bt_option(row.target)
                        };
                    });
                    bt_draw();
                    if (typeof done === 'function') {
                        done();
                    }
                });
            });
        }

        function bt_select(key) {
            bt_selected = (bt_selected === key) ? '' : key;
            $('#fp-bt-editor').data('picking', false);
            $('#fp-bt-saved').text('');
            bt_draw();
        }

        function bt_saved(message) {
            $('#fp-bt-saved').text(plain(message));
            window.setTimeout(function () { $('#fp-bt-saved').text(''); }, 4000);
        }

        function bt_assign(key, action, target) {
            if (bt_busy) {
                return;
            }
            const row = bt_rows[key];
            const fallback = bt_default(key);
            const payload = {'button': {
                'enabled': '1',
                'key': key,
                'label': plain(row ? row.label : (fallback.label || '')),
                'code': row ? row.code : (fallback.code || ''),
                'action': action,
                'target': target || ''
            }};
            const url = row ? '/api/frontpanel/settings/set_button/' + row.uuid : '/api/frontpanel/settings/add_button';
            bt_busy = true;
            ajaxCall(url, payload, function (data) {
                bt_busy = false;
                if (data && data.result === 'saved') {
                    $('#fp-bt-editor').data('picking', false);
                    bt_load(function () {
                        bt_saved("{{ lang._('Saved. The panel follows within a few seconds.') }}");
                    });
                } else {
                    const problems = (data && is_object(data.validations)) ? Object.values(data.validations).join(' ') : '';
                    show_message(BootstrapDialog.TYPE_WARNING, "{{ lang._('Buttons') }}",
                        "{{ lang._('The key could not be saved.') }}" + (problems ? '<br/><br/>' + esc(plain(problems)) : ''));
                }
            });
        }

        $('#fp-face-keys').on('click', '.fp-key', function () {
            bt_select(String($(this).attr('data-key')));
        });
        $('#fp-bt-cards').on('click keydown', '.fp-bt-card', function (event) {
            if (event.type === 'keydown' && event.key !== 'Enter' && event.key !== ' ') {
                return;
            }
            event.preventDefault();
            bt_select(String($(this).attr('data-key')));
        });
        $('#fp-bt-actions').on('click', '.fp-tile', function () {
            const action = String($(this).attr('data-action'));
            if (action === 'screen') {
                /* a screen has to be chosen before there is anything to save */
                $('#fp-bt-editor').data('picking', true);
                $('#fp-bt-actions .fp-tile').removeClass('active');
                $(this).addClass('active');
                $('#fp-bt-screens-wrap').show();
                return;
            }
            bt_assign(bt_selected, action, '');
        });
        $('#fp-bt-screens').on('click', '.fp-tile', function () {
            bt_assign(bt_selected, 'screen', String($(this).attr('data-target')));
        });
        $('#fp-bt-reset').click(function (event) {
            event.preventDefault();
            const row = bt_rows[bt_selected];
            if (!row || bt_busy) {
                return;
            }
            bt_busy = true;
            ajaxCall('/api/frontpanel/settings/del_button/' + row.uuid, {}, function () {
                bt_busy = false;
                bt_load(function () {
                    bt_saved("{{ lang._('Saved. The panel follows within a few seconds.') }}");
                });
            });
        });

        /* Aligning the text of a panel drawn as a ring: the panel shows forty different
           characters, and the one in its top-left corner says how far the text is out. */
        const ALIGN_RULER = '0123456789ABCDEFGHIJabcdefghijklmnopqrst';

        function align(what, done) {
            ajaxCall('/api/frontpanel/service/align', {'what': String(what)}, function (data) {
                if (typeof done === 'function') {
                    done(data);
                }
            });
        }

        $('#alignShowAct').click(function () {
            const $chips = $('#fp-align-chips').empty();
            for (let row = 0; row < 2; row++) {
                const $row = $('<div class="fp-align-row"/>');
                for (let column = 0; column < 20; column++) {
                    const index = row * 20 + column;
                    $row.append($('<button type="button" class="fp-chip"/>')
                        .attr('data-index', index).text(ALIGN_RULER.charAt(index)));
                }
                $chips.append($row);
            }
            align('show', function (data) {
                if (!data || data.status !== 'ok') {
                    show_message(BootstrapDialog.TYPE_WARNING, "{{ lang._('Align the text') }}",
                        "{{ lang._('The text could not be aligned.') }}" + failure_text(data));
                    return;
                }
                $('#fp-align-pick').show();
            });
        });

        $('#fp-align-chips').on('click', '.fp-chip', function () {
            align($(this).attr('data-index'), function (data) {
                $('#fp-align-pick').hide();
                if (!data || data.status !== 'ok') {
                    show_message(BootstrapDialog.TYPE_WARNING, "{{ lang._('Align the text') }}",
                        "{{ lang._('The text could not be aligned.') }}" + failure_text(data));
                    return;
                }
                bt_saved("{{ lang._('The text is aligned.') }}");
            });
        });

        $('#alignHideAct').click(function (event) {
            event.preventDefault();
            $('#fp-align-pick').hide();
            align('hide');
        });

        /* A press at the rack lights its key here and selects it - the quickest way to tell which
           drawn key is which. The first look only takes the count, so presses from before the tab
           was opened do not light anything. */
        function bt_watch() {
            if (!$('#buttons').hasClass('active') || bt_busy) {
                return;
            }
            ajaxGet('/api/frontpanel/service/presses', {}, function (data) {
                if (!data || data.status !== 'ok') {
                    return;
                }
                const counts = is_object(data.counts) ? data.counts : {};
                const total = Object.keys(counts).reduce(function (sum, key) { return sum + Number(counts[key] || 0); }, 0);
                const recent = $.isArray(data.presses) ? data.presses : [];
                if (bt_seen !== null && total > bt_seen && recent.length) {
                    const key = String(recent[recent.length - 1].key);
                    const $key = $('#fp-face-keys .fp-key').filter(function () { return $(this).attr('data-key') === key; });
                    $key.addClass('pressed');
                    window.setTimeout(function () { $key.removeClass('pressed'); }, 600);
                    if (bt_selected !== key) {
                        bt_select(key);
                    }
                }
                bt_seen = total;
            });
        }
        window.setInterval(bt_watch, BT_PRESS_MS);

        $('#buttonsTableAct').click(function () {
            const $table = $('#fp-bt-table');
            const showing = $table.is(':visible');
            $table.toggle(!showing);
            $('.fp-bt-body').toggle(showing);
            $(this).find('span').text(plain(showing ? "{{ lang._('Show as a table') }}" : "{{ lang._('Show the panel') }}"));
            if (showing) {
                bt_load();
            } else {
                reload_buttons();
            }
        });

        $("#{{ formGridButton['table_id'] }}").UIBootgrid({
            search: '/api/frontpanel/settings/search_button',
            get: '/api/frontpanel/settings/get_button/',
            set: '/api/frontpanel/settings/set_button/',
            add: '/api/frontpanel/settings/add_button/',
            del: '/api/frontpanel/settings/del_button/',
            toggle: '/api/frontpanel/settings/toggle_button/'
        });

        function reload_buttons() {
            $("#{{ formGridButton['table_id'] }}").bootgrid('reload');
        }

        function buttons_busy(busy) {
            $('#buttonsApplyAct, #buttonsFillAct, #buttonsLearnAct').prop('disabled', busy);
            $('#buttons_progress').toggleClass('fa fa-spinner fa-pulse', busy);
        }

        $('#buttonsApplyAct').click(function () {
            buttons_busy(true);
            apply_settings(function () {
                buttons_busy(false);
            });
        });

        $('#buttonsFillAct').click(function () {
            buttons_busy(true);
            ajaxCall('/api/frontpanel/settings/fill_buttons', {}, function (data) {
                buttons_busy(false);
                reload_buttons();
                if (!data || data.status !== 'ok') {
                    show_message(BootstrapDialog.TYPE_WARNING, "{{ lang._('Buttons') }}",
                        "{{ lang._('The keys could not be added.') }}" + failure_text(data));
                } else if (data.added === 0) {
                    show_message(BootstrapDialog.TYPE_INFO, "{{ lang._('Buttons') }}",
                        esc(plain("{{ lang._('Every key this appliance is known to have is already in the list.') }}")));
                }
            });
        });

        $('#buttonsLearnAct').click(function () {
            BootstrapDialog.confirm({
                title: "{{ lang._('Learn the codes from the panel') }}",
                message: esc(plain("{{ lang._('The panel stops while it learns. It then names each key on its screen in turn: press the key it names within 15 seconds. It takes up to a minute, and the panel starts again by itself afterwards.') }}")),
                type: BootstrapDialog.TYPE_INFO,
                btnCancelLabel: "{{ lang._('Cancel') }}",
                btnOKLabel: "{{ lang._('Start') }}",
                callback: function (start) {
                    if (!start) {
                        return;
                    }
                    buttons_busy(true);
                    bt_busy = true;
                    $('#buttons-note').text(plain("{{ lang._('Watch the panel: it names each key in turn.') }}"));
                    ajaxCall('/api/frontpanel/settings/learn_buttons', {}, function (data) {
                        bt_busy = false;
                        bt_seen = null;
                        $('#buttons-note').text('');
                        reload_buttons();
                        bt_load();
                        if (!data || data.status !== 'ok') {
                            buttons_busy(false);
                            show_message(BootstrapDialog.TYPE_WARNING, "{{ lang._('Learn the codes from the panel') }}",
                                "{{ lang._('The codes could not be learned.') }}" + failure_text(data));
                            return;
                        }
                        const learned = data.learned || {};
                        const names = Object.keys(learned);
                        if (names.length === 0) {
                            buttons_busy(false);
                            show_message(BootstrapDialog.TYPE_WARNING, "{{ lang._('Learn the codes from the panel') }}",
                                esc(plain("{{ lang._('No key sent anything. This panel does not send its keys by itself; if they work, LCDproc reads them.') }}")));
                            return;
                        }
                        const $list = $('<ul/>');
                        names.forEach(function (name) {
                            $list.append($('<li/>').append($('<code/>').text(name)).append(' ').append($('<code/>').text(learned[name])));
                        });
                        let message = esc(plain("{{ lang._('Learned and saved:') }}")) + $('<div/>').append($list).html();
                        if ((data.missing || []).length) {
                            message += esc(plain("{{ lang._('Not pressed in time:') }}")) + ' ' + esc(data.missing.join(', '));
                        }
                        /* a new code decides who reads the port, and that is settled when LCDd starts */
                        apply_settings(function () {
                            buttons_busy(false);
                            show_message(BootstrapDialog.TYPE_SUCCESS, "{{ lang._('Learn the codes from the panel') }}", message);
                        });
                    });
                }
            });
        });

        $('a[href="#buttons"]').on('shown.bs.tab', function () {
            bt_seen = null;
            bt_load();
        });

        /* ------------------------------------------------------------------ page plumbing */

        $('#previewRefreshAct').click(function () {
            const $icon = $(this).find('i');
            $icon.addClass('fa-spin');
            reload_preview(function () {
                $icon.removeClass('fa-spin');
            });
        });

        $('#diagnosticsRefreshAct').click(function () {
            const $icon = $(this).find('i');
            $icon.addClass('fa-spin');
            reload_diagnostics(function () {
                $icon.removeClass('fa-spin');
            });
        });

        /* Both readings cost a configd round trip, and neither is worth taking for somebody who
           is looking at a different tab. The settings tab refreshes nothing on its own: the ports
           beside the device box and the note about an empty rotation are read when the page opens
           and again when it is saved, which is when they change. */
        let ticks = 0;
        window.setInterval(function () {
            ticks += 1;
            if ($('#preview').hasClass('active') || ($('#buttons').hasClass('active') && !bt_selected)) {
                reload_preview();
            } else if ($('#diagnostics').hasClass('active') && (ticks * PREVIEW_MS) % DIAGNOSTICS_MS === 0) {
                reload_diagnostics();
            }
        }, PREVIEW_MS);

        updateServiceControlUI('frontpanel');
        reload_preview();
        reload_diagnostics();

        /* keep the selected tab in the url */
        const selected_tab = window.location.hash !== '' ? window.location.hash : '#settings';
        $('a[href="' + selected_tab + '"]').tab('show');
        $('.nav-tabs a').on('shown.bs.tab', function (e) {
            history.pushState(null, null, e.target.hash);
        });

        $('a[href="#preview"]').on('shown.bs.tab', function () {
            reload_preview();
        });

        $('a[href="#diagnostics"]').on('shown.bs.tab', function () {
            reload_diagnostics();
        });
    });
</script>

<style>
    /* Nothing here is placed with a `left` or a `right`. The mirrored stylesheets are built from
       the files under www/css, so an offset written in a page template survives into the Arabic
       layout untouched and lands against the wrong edge. Logical properties turn with the page. */

    /* Device nodes, sizes, key names and times are written left to right even when the sentence
       around them is not. Letting each one carry its own direction is what keeps a slash, a dot
       or a leading minus from being reordered by the text beside it. The same treatment goes to
       whole sentences, because until these strings are translated they are English inside a
       right-to-left page, and the bidirectional algorithm will move a trailing full stop to the
       opposite end of the line. plaintext makes each element take its direction from its own
       first strong character, with no marker characters buried in the markup. */
    [class^="fp-"],
    [class*=" fp-"],
    .tab-pane .alert,
    .tab-pane .help-block,
    .tab-pane small,
    .tab-pane td,
    .tab-pane th {
        unicode-bidi: plaintext;
        text-align: start;
    }

    .fp-alert {
        margin: 10px;
    }

    /* the heading of a section, as OPNsense's base_form draws one */
    .fp-head {
        padding-top: 5px;
        padding-bottom: 5px;
        font-size: 16px;
    }

    .fp-head small {
        font-size: 12px;
        font-weight: normal;
    }

    /* under "full help" until it is turned on */
    .fp-help {
        display: none;
    }

    /* Summary cards, the same as the coprocessor's pages: the theme's text and a faint tint of it. */
    .fp-cards { display: flex; flex-wrap: wrap; gap: 12px; padding: 0 0 15px; }
    .fp-card { flex: 1 1 200px; min-width: 190px; border: 1px solid rgba(128, 128, 128, 0.25);
               border-inline-start: 4px solid #9e9e9e; border-radius: 3px; padding: 10px 14px;
               background-color: rgba(128, 128, 128, 0.04); }
    .fp-card.ok { border-inline-start-color: #5cb85c; }
    .fp-card.warn { border-inline-start-color: #f0ad4e; }
    .fp-card.bad { border-inline-start-color: #d9534f; }
    .fp-card .k { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; opacity: 0.6; }
    .fp-card .v { font-size: 19px; font-weight: 600; line-height: 1.3; margin: 2px 0; }
    .fp-card .s { font-size: 12px; opacity: 0.7; }
    .fp-card .fa { opacity: 0.35; float: inline-end; font-size: 18px; margin-top: 2px; }

    .fp-note {
        font-size: 85%;
        opacity: 0.85;
        padding-top: 4px;
    }

    .fp-sub {
        font-size: 85%;
        opacity: 0.75;
    }

    .fp-muted {
        opacity: 0.7;
    }

    .fp-strong {
        font-weight: bold;
    }

    .fp-label {
        display: block;
        margin-top: 10px;
        margin-bottom: 4px;
    }

    .fp-keys {
        max-width: 40em;
    }

    /* a list, not a table: one press a line, newest first */
    .fp-presses {
        list-style: none;
        margin: 0;
        padding: 0;
    }

    .fp-presses > li {
        padding-top: 2px;
        padding-bottom: 2px;
    }

    .fp-port-pick {
        margin-inline-end: 6px;
        margin-top: 4px;
    }

    /* ---------------------------------------------------------------- the panel preview */

    /* The screens side by side, as many as the width takes. A warning about all of them still
       takes the whole row. */
    #preview-body {
        display: flex;
        flex-wrap: wrap;
        column-gap: 28px;
    }

    #preview-body > .alert {
        flex: 0 0 100%;
    }

    .fp-screen {
        padding: 10px 0;
        max-width: 100%;
    }

    .fp-screen-head {
        padding-bottom: 6px;
    }

    .fp-screen-name {
        font-weight: bold;
    }

    .fp-screen-note {
        padding-top: 4px;
        font-size: 85%;
    }

    /* The grid is a picture of a piece of metal, and metal does not mirror: column one is at the
       left hand end of the physical panel whichever way this page reads. So the grid alone is
       pinned to left-to-right, exactly as the faceplate drawing in the sibling plugin is, while
       everything around it follows the page. Each character also sits in a box of its own, which
       is what stops the bidirectional algorithm from reordering a row: a panel has no algorithm
       and prints what it is given, in the order it is given it. */
    .fp-lcd {
        direction: ltr;
        white-space: nowrap;
        overflow-x: auto;
        /* Drawn as the glass it stands for: a blue backlight and light characters, the way these
           character panels look on the appliance, whatever the page's theme. The colours are the
           panel's and not the theme's, so they are written here rather than taken from a class. */
        display: inline-block;
        max-width: 100%;
        padding: 8px 10px;
        margin: 2px 0 4px;
        background: #163f7a;
        color: #e9f2ff;
        border-radius: 4px;
        box-shadow: inset 0 0 0 3px #0e2c57, inset 0 2px 8px rgba(0, 0, 0, 0.45);
    }

    /* The grid has to opt out of the rule above, and this is not a nicety. `unicode-bidi:
       plaintext` tells the browser to take the direction from the content and to ignore the
       `direction` property while doing it - which is exactly what is wanted for a sentence and
       exactly what must not happen to a picture of a piece of metal. `isolate` keeps the other
       half of that rule, so the grid still takes no direction from the Arabic paragraph around
       it, while `direction: ltr` above is once again the thing that decides which end column one
       is at. It is written for every part of the grid rather than only its outer box, because
       each of these is its own box and inherits nothing about direction from the one above. */
    .fp-lcd,
    .fp-lcd-row,
    .fp-cell,
    .fp-lcd-edge {
        unicode-bidi: isolate;
    }

    .fp-lcd-row {
        line-height: 1.5;
    }

    .fp-cell {
        display: inline-block;
        width: 1.1em;
        text-align: center;
        font-family: monospace;
        font-size: 115%;
        /* the character cells of the glass: a faint grid, light enough to read past */
        border: 1px solid rgba(255, 255, 255, 0.10);
        background: rgba(255, 255, 255, 0.04);
        /* a hair of negative margin, so two neighbouring cells share one line rather than
           drawing two and making the grid look like a spreadsheet */
        margin-inline-end: -1px;
    }

    /* Everything past the last column: still drawn, because the whole point of this preview is
       to show the part of a line that never arrives, and struck through because it never does. */
    .fp-cell-cut {
        opacity: 0.45;
        text-decoration: line-through;
        border-style: dashed;
    }

    /* A character outside plain ASCII. Marked rather than hidden: what the panel draws in that
       slot is whatever its own character table holds there, and that is a thing to find out by
       looking at the panel. The colour arrives with the theme's warning class, so the border is
       told to follow whatever that turned out to be. */
    .fp-cell-odd {
        border-style: dotted;
        border-color: currentColor;
    }

    /* Where the panel stops. A plain rule rather than an arrow, which would point the wrong way
       in Arabic, and it takes its colour from the text around it so that no value written here
       has to be kept in step with a theme. */
    .fp-lcd-edge {
        display: inline-block;
        width: 0.9em;
        border-inline-start: 2px solid currentColor;
        opacity: 0.6;
        margin-inline-start: 4px;
    }

    /* The Buttons tab. The panel is a drawing of the hardware, so its colours are the panel's own
       rather than the theme's, and it stays left to right in every language. */
    .fp-bt-head {
        padding: 10px 15px;
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
        justify-content: space-between;
    }
    .fp-bt-tools .btn {
        margin-inline-start: 4px;
    }
    .fp-bt-body {
        padding: 0 15px 15px;
    }
    .fp-face {
        display: inline-block;
        max-width: 100%;
        background: linear-gradient(#22359a, #172679);
        border-radius: 8px;
        padding: 18px 22px 20px;
        box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.45), 0 2px 6px rgba(0, 0, 0, 0.25);
        margin-bottom: 12px;
    }
    .fp-face-lcd {
        font-family: "Courier New", Courier, monospace;
        font-size: 19px;
        font-weight: bold;
        line-height: 1.35;
        color: #ffffff;
        background: #8ea4e6;
        border: 3px solid #0c1452;
        border-radius: 3px;
        padding: 6px 10px;
        width: calc(20ch + 26px);
        max-width: 100%;
        white-space: pre;
        overflow: hidden;
        text-shadow: 0 0 1px rgba(255, 255, 255, 0.6);
    }
    .fp-face-line {
        height: 1.35em;
    }
    .fp-face-keys {
        display: flex;
        gap: 14px;
        margin-top: 16px;
    }
    .fp-key {
        flex: 0 1 62px;
        min-width: 0;
        height: 36px;
        padding: 0 10px;
        border-radius: 6px;
        border: 1px solid #0c1452;
        background: linear-gradient(#f7f8fc, #c8cfe6);
        color: #2b3350;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        box-shadow: 0 3px 0 #0c1452;
        transition: transform 0.08s, box-shadow 0.08s, background 0.2s;
    }
    .fp-key:hover {
        background: linear-gradient(#ffffff, #d8def0);
    }
    .fp-key.selected {
        outline: 3px solid #f0ad4e;
        outline-offset: 2px;
    }
    .fp-key.pressed {
        transform: translateY(3px);
        box-shadow: 0 0 0 #0c1452;
        background: #ffe08a;
    }
    .fp-bt-cards {
        padding: 0 0 12px;
    }
    .fp-align {
        margin-bottom: 12px;
    }
    .fp-align-head {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
    }
    .fp-align-ruler {
        display: inline-block;
        max-width: 100%;
        overflow-x: auto;
        background: #8ea4e6;
        border: 3px solid #0c1452;
        border-radius: 3px;
        padding: 6px;
        margin-bottom: 6px;
    }
    .fp-align-row {
        display: flex;
        gap: 2px;
        margin: 2px 0;
    }
    .fp-chip {
        width: 22px;
        height: 28px;
        padding: 0;
        border: 1px solid rgba(255, 255, 255, 0.35);
        border-radius: 2px;
        background: transparent;
        color: #ffffff;
        font-family: "Courier New", Courier, monospace;
        font-size: 17px;
        font-weight: bold;
        cursor: pointer;
    }
    .fp-chip:hover {
        background: rgba(255, 255, 255, 0.25);
        border-color: #ffffff;
    }
    .fp-bt-card {
        cursor: pointer;
    }
    .fp-bt-card:hover {
        background-color: rgba(128, 128, 128, 0.09);
    }
    .fp-bt-card.selected {
        box-shadow: 0 0 0 2px #f0ad4e;
    }
    .fp-bt-editor {
        border: 1px solid rgba(128, 128, 128, 0.25);
        border-radius: 3px;
        padding: 12px 14px;
        background-color: rgba(128, 128, 128, 0.04);
    }
    .fp-bt-editor-head {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        align-items: baseline;
        margin-bottom: 10px;
    }
    .fp-bt-reset {
        margin-inline-start: auto;
    }
    .fp-bt-sub {
        margin: 12px 0 6px;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        opacity: 0.6;
    }
    .fp-tiles {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
    }
    .fp-tile {
        flex: 0 1 150px;
        min-width: 120px;
        border: 1px solid rgba(128, 128, 128, 0.3);
        border-radius: 3px;
        padding: 10px 8px;
        background-color: rgba(128, 128, 128, 0.04);
        color: inherit;
        text-align: center;
        cursor: pointer;
    }
    .fp-tile .fa {
        display: block;
        margin: 0 auto 4px;
        font-size: 20px;
        opacity: 0.7;
    }
    .fp-tile:hover {
        border-color: rgba(128, 128, 128, 0.6);
    }
    .fp-tile.active {
        border-color: #5cb85c;
        box-shadow: inset 0 0 0 1px #5cb85c;
        background-color: rgba(92, 184, 92, 0.08);
    }
    .fp-tile-small {
        flex-basis: 120px;
        padding: 7px 8px;
    }
    .fp-buttons-bar {
        padding: 10px 15px 15px;
    }
    .fp-buttons-bar .btn {
        margin-inline-end: 6px;
        margin-bottom: 4px;
    }
    @media (min-width: 768px) {
        #buttons .tabulator-tableholder {
            overflow-x: hidden;
        }
    }
</style>

<div class="fp-cards" id="fp-cards"></div>

<ul class="nav nav-tabs" data-tabs="tabs" id="maintabs">
    <li><a data-toggle="tab" href="#settings">{{ lang._('Settings') }}</a></li>
    <li><a data-toggle="tab" href="#buttons">{{ lang._('Buttons') }}</a></li>
    <li><a data-toggle="tab" href="#preview">{{ lang._('Preview') }}</a></li>
    <li><a data-toggle="tab" href="#diagnostics">{{ lang._('Diagnostics') }}</a></li>
</ul>

<div class="tab-content content-box" id="frontpanel">
    <div id="settings" class="tab-pane fade in">
        <div id="rotation-note"></div>
        {{ partial("layout_partials/base_form", ['fields': generalForm, 'id': 'frm_general', 'apply_btn_id': 'saveAct']) }}
    </div>

    <div id="buttons" class="tab-pane fade in">
        <div class="fp-bt-head">
            <span class="text-muted">{{ lang._('Click a key on the drawing, or press it on the panel, then choose what it does.') }}</span>
            <span class="fp-bt-tools">
                <button id="buttonsLearnAct" class="btn btn-default btn-xs" type="button">
                    <i class="fa fa-fw fa-hand-pointer-o"></i> {{ lang._('Learn the codes from the panel') }}
                </button>
                <button id="buttonsTableAct" class="btn btn-default btn-xs" type="button">
                    <i class="fa fa-fw fa-table"></i> <span>{{ lang._('Show as a table') }}</span>
                </button>
                <i id="buttons_progress"></i>
            </span>
        </div>
        <div class="fp-bt-body">
            {# A drawing of the hardware, so it stays left to right in every language. #}
            <div class="fp-face" dir="ltr">
                <div class="fp-face-lcd" id="fp-face-lcd"><div class="fp-face-line"></div><div class="fp-face-line"></div></div>
                <div class="fp-face-keys" id="fp-face-keys"></div>
            </div>
            <div id="fp-align" class="fp-align" style="display: none;">
                <div class="fp-align-head">
                    <span class="text-muted">{{ lang._('If the text on the panel starts in the wrong place, show the ruler and pick the character in its top-left corner.') }}</span>
                    <button id="alignShowAct" class="btn btn-default btn-xs" type="button">
                        <i class="fa fa-fw fa-arrows-h"></i> {{ lang._('Align the text') }}
                    </button>
                </div>
                <div id="fp-align-pick" style="display: none;">
                    <div class="fp-bt-sub">{{ lang._('The ruler is on the panel. Click the character you see in its top-left corner - or move the text with the arrow keys on the panel until 0 is there, then press Enter.') }}</div>
                    <div class="fp-align-ruler" dir="ltr" id="fp-align-chips"></div>
                    <a href="#" id="alignHideAct">{{ lang._('Cancel') }}</a>
                </div>
            </div>
            <div id="buttons-note" class="fp-note text-info"></div>
            <div class="fp-cards fp-bt-cards" id="fp-bt-cards"></div>
            <div class="fp-bt-editor" id="fp-bt-editor" style="display: none;">
                <div class="fp-bt-editor-head">
                    <b id="fp-bt-editing"></b>
                    <span class="fp-bt-saved text-success" id="fp-bt-saved"></span>
                    <a href="#" id="fp-bt-reset" class="fp-bt-reset">{{ lang._('Back to the default') }}</a>
                </div>
                <div class="fp-tiles" id="fp-bt-actions"></div>
                <div id="fp-bt-screens-wrap" style="display: none;">
                    <div class="fp-bt-sub">{{ lang._('Which screen') }}</div>
                    <div class="fp-tiles" id="fp-bt-screens"></div>
                </div>
            </div>
        </div>
        <div id="fp-bt-table" style="display: none;">
            {{ partial('layout_partials/base_bootgrid_table', formGridButton + {'command_width': '120'}) }}
            <div class="fp-buttons-bar">
                <button class="btn btn-primary" id="buttonsApplyAct" type="button">
                    <b>{{ lang._('Apply') }}</b>
                </button>
                <button class="btn btn-default" id="buttonsFillAct" type="button">
                    <i class="fa fa-fw fa-list"></i> {{ lang._('Add this appliance\'s keys') }}
                </button>
            </div>
        </div>
    </div>

    {# The two other tabs are laid out the way OPNsense lays out a form: sections with a heading,
       a label on the left and the reading on the right, and the long explanations under the
       same "full help" switch the settings tab has. #}
    <div id="preview" class="tab-pane fade in">
        <div class="table-responsive">
            <table class="table table-striped table-condensed fp-form">
                <thead>
                    <tr>
                        <th>
                            <div class="fp-head">
                                <b>{{ lang._('Screens') }}</b>
                                <small id="preview-summary" class="fp-sub">{{ lang._('Asking the firewall what the panel would show...') }}</small>
                                <span class="pull-right">
                                    <i class="fa fa-info-circle fa-sm fa-fw text-primary"></i> <small>{{ lang._('full help') }}</small>
                                    <a href="#" class="fp-help-toggle"><i class="fa fa-toggle-off fa-fw text-danger"></i></a>
                                    <button id="previewRefreshAct" class="btn btn-xs btn-default" type="button" title="{{ lang._('Refresh') }}">
                                        <i class="fa fa-fw fa-refresh"></i>
                                    </button>
                                </span>
                            </div>
                        </th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>
                            <div class="help-block fp-help">
                                {{ lang._('Each screen as the panel would draw it this second, at the width of the display. Anything past the last column is shown struck through: that part never reaches the panel. Nothing here is sent to the display, so it can be read with the service stopped.') }}
                            </div>
                            <div id="preview-body"></div>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <div id="diagnostics" class="tab-pane fade in">
        <div class="table-responsive">
            <table class="table table-striped table-condensed fp-form">
                <colgroup>
                    <col style="width: 25%;"/>
                    <col style="width: 75%;"/>
                </colgroup>
                <thead>
                    <tr>
                        <th colspan="2">
                            <div class="fp-head">
                                <b>{{ lang._('Service') }}</b>
                                <span class="pull-right">
                                    <i class="fa fa-info-circle fa-sm fa-fw text-primary"></i> <small>{{ lang._('full help') }}</small>
                                    <a href="#" class="fp-help-toggle"><i class="fa fa-toggle-off fa-fw text-danger"></i></a>
                                    <button id="diagnosticsRefreshAct" class="btn btn-xs btn-default" type="button" title="{{ lang._('Refresh') }}">
                                        <i class="fa fa-fw fa-refresh"></i>
                                    </button>
                                </span>
                            </div>
                        </th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>{{ lang._('Status') }}</td>
                        <td id="service-state"></td>
                    </tr>
                </tbody>
                <thead>
                    <tr><th colspan="2"><div class="fp-head"><b>{{ lang._('Keys') }}</b></div></th></tr>
                </thead>
                <tbody>
                    <tr><td colspan="2" id="keys-body"></td></tr>
                </tbody>
                <thead>
                    <tr><th colspan="2"><div class="fp-head"><b>{{ lang._('Serial ports on this machine') }}</b></div></th></tr>
                </thead>
                <tbody id="devices-body"></tbody>
                <thead class="fp-suggestion" style="display: none;">
                    <tr><th colspan="2"><div class="fp-head"><b>{{ lang._('Known panel') }}</b></div></th></tr>
                </thead>
                <tbody id="suggestion-body" class="fp-suggestion" style="display: none;"></tbody>
                <thead>
                    <tr><th colspan="2"><div class="fp-head"><b>{{ lang._('Test the panel') }}</b></div></th></tr>
                </thead>
                <tbody>
                    <tr>
                        <td>{{ lang._('A line for the panel') }}</td>
                        <td>
                            <input type="text" id="test-text" class="form-control fp-tech" maxlength="64"
                                   style="max-width: 24em; display: inline-block;"
                                   placeholder="{{ lang._('a line to put on the panel') }}"/>
                            <button id="testAct" class="btn btn-default" type="button">
                                <i class="fa fa-fw fa-paper-plane"></i> {{ lang._('Send it') }}
                            </button>
                            <div class="help-block fp-help">
                                {{ lang._('Put one line on the panel for a moment and then give it back to the rotation. It goes through LCDproc like every other screen, so it only works while the service is running.') }}
                            </div>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
</div>

{{ partial("layout_partials/base_dialog", ['fields': buttonForm, 'id': formGridButton['edit_dialog_id'], 'label': lang._('Edit button')]) }}
