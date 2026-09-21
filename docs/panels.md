# Adding your appliance to `panels.json`

The table this plugin ships has **one confirmed entry**: an ex-Sophos XG 330 rev 2, whose display has
been watched working and photographed, and whose four keys were then measured one button at a time.
That is the honest state of the hardware support, and this page is how a second entry gets added to
it.

There is no code to write. An appliance entry is one block of JSON that says: this is how to
recognise the machine, this is the LCDproc driver its panel needs, these are that driver's settings,
and this is what somebody actually confirmed. The plugin never applies the block by itself — it
fills the settings form in with the proposal and waits for a human to press Apply — so the worst a
wrong entry can do is waste your evening, not your firewall's.

Everything marked **measured here** was read from the reference machine, an ex-Sophos XG 330 rev 2
running OPNsense 26.7.4_1 / FreeBSD 15.1. The commands below are the ones that produced it.

---

## Three rules before you point anything at a serial port

Read these even if you skip everything else. They are the whole risk in this exercise, and they are
all avoidable.

**1. The port must not be carrying a console.** A serial console is a real login session on a real
tty. Writing display bytes at it fights a getty for the line, and on a machine you are managing over
that console it is also the rope you were standing on. Section 2 shows how to find out which port is
the console on your machine; it takes one command.

**2. An unknown protocol on an unknown device can leave a panel confused.** A character LCD
interprets bytes as commands as well as text: a stream it does not understand can shift the display
window, load garbage into its user-defined characters, put the cursor somewhere impossible, or leave
it blank. This is not damage and nothing is broken, but the panel may well stay in that state until
it is **power-cycled** — and power-cycled means the power actually going away, not a reboot, because
a panel that keeps its supply keeps its contents. On an appliance that means shutting down, pulling
the cord, and counting to ten. Do this at a time when you can afford to do that.

**3. One process owns a port at a time.** If a daemon already has the port open, a second one gets
an error or, worse, the two interleave their bytes. Stop the plugin's service before you run LCDd by
hand, and check the port is free before either.

There is a fourth, softer rule: do not do this on the firewall carrying the household's traffic at
nine in the evening. The commands in sections 1 to 4 are all read-only and can be run any time; it is
section 5, where something first writes to the port, that wants a quiet hour.

---

## 1. Work out which box this is

Recognition uses the identity the BIOS reports through SMBIOS, exactly as my other plugin does for
chassis port labels:

```sh
kenv | grep -E '^smbios\.(planar|system)\.(maker|product|version)'
```

On the reference machine (measured here):

```
smbios.planar.maker="Sophos"
smbios.planar.product="XG"
smbios.planar.version="330r2"
smbios.system.maker="Sophos"
smbios.system.product="XG"
smbios.system.version="330r2"
```

Three things to notice, because each of them catches somebody out:

- **Appliance vendors fill in very little.** Most of the other SMBIOS fields on this board say
  `Default string`. That is a *value*, not an empty field, and matching on it would claim every other
  appliance whose vendor was equally careless. Never put `Default string` in a `match`.
- **The model number usually hides in `version`.** `product` here is just `XG`; the `330r2` that
  tells you which XG it is lives in `version`. That is the ordinary shape of appliance SMBIOS.
- **`kenv` output contains your serial number.** `smbios.system.serial` is a real identifier of your
  machine. Redact it before you paste the output into a public issue; nothing here needs it.

If all three of `maker`, `product` and `version` are useless on your box, stop and say so in the
issue rather than inventing a match. An appliance that does not identify itself needs a different
approach, and I would rather know that than guess.

## 2. Find the panel's serial port — and the one you must not touch

Three questions, three commands.

**Which serial ports exist?**

```sh
ls /dev/cua*
dmesg | grep -i uart
```

Measured here:

```
/dev/cuau0  /dev/cuau0.init  /dev/cuau0.lock  /dev/cuau1  /dev/cuau1.init  /dev/cuau1.lock

uart0: <16550 or compatible> port 0x3f8-0x3ff irq 4 flags 0x10 on acpi0
uart0: console (115200,n,8,1)
uart1: <16550 or compatible> port 0x2f8-0x2ff irq 3 on acpi0
```

Two ports: `uart0` at the traditional COM1 address and `uart1` at COM2. `uartN` is `/dev/cuauN` for
outgoing use, which is what a display driver wants, and `/dev/ttyuN` for incoming — that second name
is the one a getty uses, and it is the reason the next question matters.

**Which one is the console?**

```sh
sysctl -n kern.console
grep ttyu /etc/ttys
```

Measured here:

```
ttyu0,ttyv0,/ttyu0,ucom,ttyv0,

ttyu0	"/usr/libexec/getty 3wire.115200"	vt100	onifconsole secure
ttyu1	"/usr/libexec/getty 3wire.115200"	vt100	onifconsole secure
ttyu2	"/usr/libexec/getty 3wire.115200"	vt100	onifconsole secure
ttyu3	"/usr/libexec/getty 3wire.115200"	vt100	onifconsole secure
```

`/etc/ttys` carries a line for four serial ports whether the machine has four or not, which is why
there are more lines there than there are ports in `dmesg`. What decides the matter is the first
command: `kern.console` names `ttyu0`, and notice `onifconsole` in `/etc/ttys` — FreeBSD starts a
getty on those ports **only** on the one the loader made the console. So `ttyu1` — and therefore
`/dev/cuau1` — carries no login session on this machine, which is what makes it safe to drive a
panel with. Check
this on your own box before you go further. If your only serial port is the console, you do not have
a port for a panel, and no setting in this plugin changes that.

**Is anything holding it already?**

```sh
fstat /dev/cuau1
```

Measured here, with the plugin's LCDd running:

```
USER     CMD          PID   FD MOUNT      INUM MODE         SZ|DV R/W NAME
nobody   LCDd       35859    4 /dev         83 crw-rw----   cuau1 rw  /dev/cuau1
```

An empty result (a header line and nothing else) means the port is free. A line naming some other
daemon means you have found what the port is really for; leave it alone.

That output also shows a detail worth knowing: `/dev/cuau1` is `uucp:dialer` mode 0660, which no
ordinary user can open, and yet LCDd holds it as `nobody`. LCDd opens its device while it is still
root and drops privileges afterwards. You do not need to loosen any permissions to make a panel
work, and you should not.

**Which port is the panel on?** If the machine has two ports and one is the console, you have your
answer by elimination — and on this appliance that elimination was correct. Otherwise the evidence
comes from section 3, or from opening the case: these panels are daughterboards on a short cable,
and the header they land on is usually silk-screened.

While the case is open, count the character cells on the glass. Sixteen columns by two rows is by far
the most common appliance panel; twenty by two and twenty by four also exist. That count is the
`Size` setting, and getting it wrong is one of the ways a working driver looks broken.

## 3. Find out what the vendor's own firmware used

This is the single most valuable piece of evidence, and it is worth an hour of looking, because it
turns the question from "which of 36 drivers?" into "which settings?".

Appliance vendors overwhelmingly did not write panel code either. On the reference machine, Sophos's
own firmware drove this panel with **LCDproc's own daemon on `/dev/ttyS1`** (reported — read from
descriptions of the original firmware, not verified here). The moment that was known, the shape of
the answer was known: the panel speaks something LCDproc already supports, on the second serial port,
and everything left is which connection type and what speed.

Where that evidence lives, roughly in order of how much it is worth:

- **The original firmware, if the disk still exists.** Mount it read-only and look for LCDproc's own
  files: `LCDd.conf`, `lcdproc.conf`, an rc script named `LCDd`, a binary called `lcdd` or `LCDd`. A
  vendor's `LCDd.conf` is the entry you are trying to write, already written.
- **The vendor's GPL source release.** LCDproc is GPLv2, so a vendor shipping it owes you the source
  and usually their patches with it. Search the vendor's open-source page for `lcdproc`.
- **Teardowns, forum threads and other people's notes** for the same model. Treat these as reported,
  not verified, and say so in your entry.
- **The device name in that evidence translates.** Linux `/dev/ttyS0` is FreeBSD `/dev/cuau0`, and
  `/dev/ttyS1` is `/dev/cuau1`. A vendor config pointing at `ttyS1` is pointing at the port this
  plugin would call `cuau1`.

If the vendor used something that is not LCDproc, you may still be lucky: the drivers in section 4
were written for somebody's appliance originally, and the names in that list are often the names of
the appliances themselves.

## 4. Choose a driver out of the thirty-six

**The authoritative list is on your own disk:**

```sh
ls /usr/local/lib/lcdproc/
```

Measured here, 36 modules — the names below are how each one is spelled in a configuration file, and
on disk each carries a `.so` suffix:

```
CFontz    CFontzPacket  CwLnx     EyeboxOne  IOWarrior  MD8800
MtxOrb    NoritakeVFD   SureElec  bayrad     curses     ea65
glcd      glk           hd44780   icp_a106   lb216      lcdm001
lcterm    ms6931        mtc_s16209x          picolcd    pyramid
rawserial sdeclcd       sed1330   sed1520    serialPOS  serialVFD
shuttleVFD  sli         stv5730   t6963      text       tyan
vlsys_m428
```

**Do not take the list from `LCDd.conf.sample`.** The comment above its `Driver=` line names every
driver LCDproc *can* build — `svga`, `xosd`, `ula200`, `glcdlib`, `imon`, `lirc`, `g15`, `linux_input`
and more — and this package builds none of those (measured here: they have no `.so`). Configuring one
of them produces a load failure and a confusing evening.

**The documentation you have is that same sample file.** Every driver has a section in it with
comments explaining its options, and reading the section is how you find out what a driver expects
before you give it a port:

```sh
grep -n '^\[' /usr/local/etc/LCDd.conf.sample
sed -n '/^\[mtc_s16209x\]/,/^\[MtxOrb\]/p' /usr/local/etc/LCDd.conf.sample
```

Those sections carry real information. `icp_a106`'s comments name the panels it supports and what a
short and a long press of each key report (measured here). `mtc_s16209x` takes a device, a brightness
and a reboot flag — and **no keypad options at all**, which is how you know before you start that
that driver can light a screen and can never read a button. `sdeclcd`'s section is literally
`# No options`. Some of these drivers are one decision, not twenty.

**Narrow by how the panel is attached:**

| The panel is… | Try, roughly in this order |
| --- | --- |
| character rows on a **serial port** (the appliance case) | `hd44780` with the right `ConnectionType`, then the vendor-specific serial drivers: `mtc_s16209x`, `icp_a106`, `lcdm001`, `lcterm`, `lb216`, `MtxOrb`, `CFontz` / `CFontzPacket`, `CwLnx`, `SureElec`, `sdeclcd`, `vlsys_m428` |
| a **vacuum-fluorescent** display | `serialVFD`, `NoritakeVFD`, `shuttleVFD` |
| on **USB** | `picolcd`, `IOWarrior`, or `hd44780` with one of its USB connection types |
| **pixel-addressable**, not character cells | `glcd`, `sed1330`, `sed1520`, `t6963` |
| **not there at all** — you are testing the plugin's screens with no hardware | `text` or `curses`, which draw to a terminal instead of to glass |

That last row is not a joke and it is the cheapest way to start: choose `text`, and the screens this
plugin generates are rendered where you can read them, with no serial port involved and nothing to
power-cycle. It proves your screens, your speeds and your settings before the panel is ever part of
the question.

**`hd44780` is a family, not a driver.** Most appliance panels are HD44780-compatible glass behind
some adapter, and `ConnectionType` selects the adapter. The one on this machine is `ezio`
(measured here). To check that a name is compiled into the module you actually have:

```sh
strings -a /usr/local/lib/lcdproc/hd44780.so | grep -x ezio
```

Measured here, these names are present in the shipped module: `4bit`, `8bit`, `serialLpt`, `winamp`,
`lcdserializer`, `los-panel`, `picanlcd`, `lcm162`, `ezio`, `pertelian`, `lis2`, `mplay`, `vdr-lcd`,
`vdr-wakeup`, `usblcd`, `lcd2usb`, `bwctusb`, `usbtiny`, `usb4all`, `uss720`, `piplate`, `ethlcd`.
What each one means is in LCDproc's own hd44780 documentation; what matters here is that a name that
does not come back from that command is not going to work whatever the documentation says.

**What to try first**, on an x86 appliance with two character rows on a serial port and a few keys
beside the glass: `hd44780`, `ConnectionType=ezio`, `Size=16x2`, `Keypad=yes`, at the 2400 baud that
connection type uses by default. That is what this appliance turned out to be, and that class of
hardware — a small serial adapter driving HD44780 glass with a four-key pad — is common enough that it
is the right first guess. Reading the symptom table in section 5 is faster than guessing a second
time.

Note that the sample configuration file uses **Linux device names** throughout: its `Device=` lines
say `/dev/ttyS0`, `/dev/ttyS1`, `/dev/lcd`. On FreeBSD you want `/dev/cuau0`, `/dev/cuau1`.

## 5. Try it, safely

**The easy way is the plugin itself.** Put your driver, device and size into **System → Front Panel**
and press Apply. The port check, the configuration file and the service are then handled for you, and
turning the plugin off again stops everything. If the glass lights up, you are done and section 6 is
five minutes of typing.

**By hand is what was done here**, and it is worth knowing because it gives you LCDd's own report
output while you watch the panel. Turn the plugin off on its settings page first, so that two servers
are not fighting for the same port, then write a small configuration under `/root` and run the server
in the foreground.

This is the working configuration from the reference machine, `/root/frontpanel/LCDd-ezio.conf`, with
its comments translated (measured here — this is the file behind the photograph) and with one line
group corrected afterwards: the `KeyMatrix_` names below are the map that was later measured a button
at a time, not LCDproc's default order, which on this panel turns out to be wrong. The keys note at
the end of this section is the whole story. Copy it as your starting point and change the driver
section to whatever you are testing:

```ini
[server]
DriverPath=/usr/local/lib/lcdproc/
Driver=hd44780
Bind=127.0.0.1
Port=13666
User=nobody
ReportLevel=3
ReportToSyslog=no
ServerScreen=off
# three seconds a screen instead of six
WaitTime=3
# faster scrolling for long titles
TitleSpeed=10
# the heartbeat is a user-defined character this panel cannot draw: it comes out as a
# solid black block in the corner. Turning it off removed half of what looked "irregular".
Heartbeat=off

[hd44780]
ConnectionType=ezio
Device=/dev/cuau1
Size=16x2
Keypad=yes
# measured one key at a time on this panel; LCDproc's own default order is different
KeyMatrix_4_1=Down
KeyMatrix_4_2=Escape
KeyMatrix_4_3=Up
KeyMatrix_4_4=Enter
# double the delay rather than quadruple: faster, and still safe with the full refresh below
DelayMult=2
DelayBus=yes
RefreshDisplay=4
KeepAliveDisplay=2
```

Run it in the foreground, where you can read every line it says:

```sh
/usr/local/sbin/LCDd -f -c /root/frontpanel/LCDd-ezio.conf
```

and in a second shell give it something to show, using LCDproc's own demo client:

```sh
/usr/local/bin/lcdproc -c /usr/local/etc/lcdproc.conf.sample C M U T
```

`C M U T` are its CPU, memory, uptime and time screens, and the sample file that ships with the
package is a perfectly good client configuration to point it at — it already talks to `localhost`
on port 13666, which is where the server above is listening. That client is part of the `lcdproc`
package, and it is the quickest way to find out whether the panel and the driver agree, before this
plugin's own screens are anywhere in the picture.

**Read the glass, not your expectations.** What you see narrows it down:

| What the panel does | What it usually means |
| --- | --- |
| The vendor's old text is still there, unchanged | nothing is reaching the panel: wrong port, wrong wiring, or LCDd never opened the device — check its report output |
| Nothing at all, backlight on, glass blank | LCDd is talking, the panel is listening, and the bytes are not text it understands. Wrong connection type, or the wrong speed |
| Solid black blocks on a whole line | classic "controller initialised at the wrong size or the wrong interface width" — check `Size`, and for `hd44780`, the connection type |
| Right text, one solid black block in a corner | the heartbeat. Set `Heartbeat=off` |
| Right text with characters missing or shifted | the panel cannot keep up: raise `DelayMult` to 2, then 4 |
| Right text that goes wrong after a while and stays wrong | set `RefreshDisplay` to a few seconds so a full redraw cleans it up |
| Right text, and nothing at all from the keys | three different causes, and the keys note below tells them apart: the report level is too low to print a press, the driver is not polling, or the display traffic is swallowing the poll |
| Right text, and the log says `handle_input: left over key` | the panel reported a press, the driver decoded it, and **no client had claimed that key**, so nothing happened. The keypad works. People swap drivers for hours over this line |

**If the panel ends up in a state nothing fixes, power-cycle the appliance** — power off, wait, power
on. A reboot alone may not do it, because the panel keeps its contents while it keeps its supply.
Nothing you can send down a serial line damages one of these; the worst case really is a confused
display and a walk to the rack.

**About the keys.** On this family of panels the keys are *polled*: the host sends a poll byte and
the panel answers (documented in LCDproc's `hd44780-serial.c`). Listening to the port passively shows
nothing whether the keys work or not, so "I saw no key events" is not evidence that a panel has no
working keypad. On the reference machine all four keys report (measured here, 2026-09-21), and it
took two corrections to the obvious procedure to see the first one:

- **`ReportLevel=3` is not enough, and `5` is more than you want.** The runs at level 3 logged
  nothing while keys were being pressed; the first runs that recorded a press were at
  `ReportLevel=5` (measured here). Level 4 was measured afterwards and is the one to use: it writes
  `Driver [hd44780] generated keystroke Down` for every press and nothing else, while level 5 adds
  LCDd's own debug narration — `screenlist_process()` once per frame, eight times a second, which is
  around 700,000 lines a day and rotates the very history you are reading away within minutes. The
  plugin asks for level 4 whenever the keypad is switched on, so an installed panel needs no change
  here at all.

  The driver's own line — `HD44780_get_key: Key pressed: Down (4,1)`, the one that names the matrix
  position — has only been seen at level 5, and whether level 4 carries it has not been measured. It
  does not matter for a panel this plugin configured: the name in the log and the map in
  `LCDd.conf` name the same row, so the plugin reads the position back out of the map it wrote. It
  matters only if you are measuring a panel by hand with an unknown map, which is exactly when
  setting `ReportLevel=5` for the length of the test is the right thing to do.
- **Quiet the screen while you test.** At 2400 baud the display and the keypad share one line, and
  writing starves polling: with screens changing every 3 seconds and a full redraw every 4, two
  thirds of the presses were lost (measured here). With the screen held still — `WaitTime=60`,
  `RefreshDisplay=0`, `KeepAliveDisplay=0` — every press arrived. This is worth knowing beyond the
  test: a panel whose keys feel unreliable in normal use is usually a panel being written to too
  often, not a panel with a bad keypad.

Then **map one key at a time**, because the names in `KeyMatrix_4_1` … `KeyMatrix_4_4` are labels you
choose and not something the panel tells you. Press one button three times, read which position the
log reports, and write that button's name at that position:

```
HD44780_get_key: Key pressed: Down (4,1)
Driver [hd44780] generated keystroke Down
```

On this appliance the answer was ▼ at 4,1, ESC at 4,2, ▲ at 4,3 and ENTER at 4,4 — which is **not**
LCDproc's shipped order for this connection type; the sample configuration would put `Enter` on 4,1,
where the down arrow actually is. A panel wired to the sample's defaults scrolls the wrong way, and
that is why the map is part of the appliance entry rather than left to the driver.

If nothing appears after a minute of pressing at level 5 with the screen quiet, record that as
unproven rather than as broken, and say so in your entry.

## 6. Write the entry

Entries live in `panels.json` — in this repository at
`src/opnsense/scripts/frontpanel/panels.json`, and on an installed firewall at
`/usr/local/opnsense/scripts/frontpanel/panels.json`. The file has four parts at the top level:
`version`, the `panels` object that holds the entries, a `drivers` fallback table of option names,
and `speed_options`, which records where each adjustable speed lands in `LCDd.conf`. **Only `panels`
concerns you.** Add your block beside the others inside it. This is the shipped entry, with its
longer notes trimmed to one line, and it is the whole shape:

```json
{
  "panels": {
    "sophos-xg-3xx": {
      "display": "Sophos XG / XGS front panel",
      "match": {"maker": "^Sophos$", "product": "^XG$"},
      "driver": "hd44780",
      "options": {"ConnectionType": "ezio", "Device": "/dev/cuau1", "Size": "16x2", "Keypad": "yes"},
      "keymap": {
        "KeyMatrix_4_1": "Down",
        "KeyMatrix_4_2": "Escape",
        "KeyMatrix_4_3": "Up",
        "KeyMatrix_4_4": "Enter"
      },
      "confirmed": "XG 330 rev 2 (smbios version 330r2), 2026-09-21: display verified by photograph; all four keys measured one at a time.",
      "notes": [
        "ConnectionType=ezio fixes the line at 2400 baud by itself, so no Speed option is written."
      ]
    }
  }
}
```

| Key | What it is |
| --- | --- |
| the entry name (`sophos-xg-3xx`) | your key for the entry: lower case, vendor and model, no spaces. Keep it recognisable — it is how the entry is referred to when somebody reports a problem with it. |
| `display` | a readable name for the entry — the name a person would use for the machine, not the key. It is carried with the entry so that a page, or a bug report, can name the appliance rather than quote the key. |
| `match` | the SMBIOS values from section 1, each one a **regular expression**. Anchor them: `"^XG$"` matches this board and not `XGS`, while an unanchored `"XG"` would claim both. A value containing a `.`, a `+` or brackets is a pattern, not text — escape it. Every field you name has to match, so name the smallest set that identifies the machine. An entry with an empty `match` never matches anything; that is how `generic` stays out of the way. |
| `driver` | the LCDproc driver, spelled exactly as the module in `/usr/local/lib/lcdproc/` is spelled. Driver names are case sensitive: `CFontzPacket`, not `cfontzpacket`. |
| `options` | that driver's own settings, with the names LCDproc uses for them — they are written into the driver's section of the generated configuration verbatim. Take the names from the driver's section in `LCDd.conf.sample`; do not invent them, because a name LCDproc does not know is silently ignored and you will spend an evening on it. `Device`, `Size` and `Keypad` are a special case: they belong on the settings page, so the entry's values for them are offered as the proposal that fills the form in, and the generated configuration then takes them from the form rather than from here. |
| `keymap` | what to call each key, for a driver that can read them. The names on the left are **LCDd's own option names** — `KeyMatrix_4_1`, not `4_1` — because they are written into the driver's section exactly as they are spelled here. Measure them a key at a time (section 5); do not copy the sample configuration's order, which is wrong on at least one real appliance. Leave the whole block out for a driver with no keypad. |
| `confirmed` | **a sentence, not a flag.** What was confirmed, on which model, and when. The page shows it to whoever is about to press Apply, so write it for them. An empty string is the honest value for an entry nobody has watched work. |
| `notes`, `hint` | optional prose kept with the entry, and read by people rather than by code: `notes` for what the next person needs to know about this panel, `hint` for what to try when the entry is admittedly a guess. Neither is applied to anything. The one sentence the page puts in front of whoever is about to press Apply is `confirmed`, so what matters most belongs there. |

Three habits that make the table worth trusting:

- **Match the family, not the serial number.** The shipped entry matches any Sophos XG, because the
  panel is a property of that chassis family rather than of one model, and the entry only ever fills
  a form in. If your appliance shares SMBIOS strings with a cousin that has a *different* panel, do
  not widen the entry to cover both — say so in the pull request, and the matching gets the extra
  field it needs rather than the table getting a wrong proposal.
- **Specific entries go above general ones.** The first entry whose stated fields all match is the
  one used, so a broad `{"maker": "^Sophos$"}` entry placed above a precise one would swallow it.
- **An unconfirmed entry is allowed — but it has to say so.** "Not confirmed: taken from the vendor's
  own LCDd.conf, never run on this hardware" is a perfectly good `confirmed` value and an honest
  contribution. What is not acceptable is a confident sentence about a panel nobody watched light up.

## 7. Check it

**Does the file still parse?** A broken `panels.json` is the one way to make the proposals disappear:

```sh
python3 -c 'import json; json.load(open("/usr/local/opnsense/scripts/frontpanel/panels.json", encoding="utf-8")); print("ok")'
```

**Does the page find your entry?** Open **System → Front Panel** and reload it. The form should come
up filled in with your driver, your device and your size, and the page should show your `confirmed`
sentence back to you. If it proposes nothing, the `match` did not match — re-read the three `kenv`
values from section 1 and look for a stray anchor or a capital letter. If it proposes somebody
*else's* entry, yours is below a broader one in the file; move it up.

**Does the panel agree?** Press Apply and walk to the front of the appliance. This is the only check
that counts, and it is the one that decides what you are allowed to write in `confirmed`.

**Do the keys report?** Use the key test on the settings page and press each key once. It answers
with the matrix position that spoke, which is the thing your `keymap` is about: check that the button
printed ▲ really is the position you called `Up`, because a map copied from the sample configuration
is a coin toss. Whatever it says — a position, or nothing at all — write it down. Both results are
useful; only a guess is not.

## 8. Send it in

Open a pull request adding your block to `src/opnsense/scripts/frontpanel/panels.json`, above any
broader entry that would also match your board, and put this in the description:

- the `kenv | grep -E '^smbios\.(planar|system)\.(maker|product|version)'` output, verbatim —
  **with the serial number redacted** if you paste more than those lines;
- the model as it is printed on the front of the box, and the panel's size in characters, counted off
  the glass;
- the `dmesg | grep -i uart` lines, and which port the panel is on;
- `sysctl -n kern.console` and the `grep ttyu /etc/ttys` lines, showing that the port you used is not
  the console;
- the LCDd configuration that worked, in full;
- **a photograph of the panel showing your own text.** There is no substitute for it. A screenshot
  proves the software ran; only the glass proves the panel lit;
- what the keys did: which driver, which matrix position each printed button reported at, and how
  long you pressed them for. "Nothing after two minutes of pressing, at `ReportLevel=5` with the
  screen held still" is a result and it belongs in the entry — but say that you tested it that way,
  because a silent keypad at level 3, or with a screen being redrawn every few seconds, proves
  nothing at all;
- what you did *not* check. If you confirmed the display on an XG 230 and are assuming the 330 is the
  same panel, say so — that sentence is the difference between a table somebody can trust and a table
  somebody has to re-check.

If the answer turned out to be a driver nobody has used here, say what you tried before it as well.
The list of 36 is short, but going through it blind is an evening, and the next person with your
appliance should not have to spend it.

---

BSD 2-Clause, the same as the rest of this plugin. Written by
`Abdelmonem Awad <eg2@live.com>`.
