# Security

## Reporting a vulnerability

**Not in a public issue, please.** Report it privately through GitHub -
[**Report a vulnerability**](https://github.com/AbdelmonemAwad/os-frontpanel/security/advisories/new),
on the Security tab - where only you and the owner see it, and the fix can be prepared before anything is
public. Without a GitHub account, write to **security@npuforge.org**. Either way, include:

- what is affected - the panel service, the actions its keys run, its page and its configd actions;
- the appliance, the version you installed, and the OPNsense version;
- how to reproduce it, and what you saw.

This is one person's project, worked on in the evenings: expect an answer within days, not hours.
A fix is made in a pull request and the reporter credited in it, unless they ask not to be.

## What is supported

The newest version on `main`, and the newest release where there are releases. Fixes go there,
with no backports.

## Worth knowing before you report

- **The keys on the front run actions on the appliance.** A key that does something its page did not assign, or an action reachable without the GUI's login, is a vulnerability.
- The screen shows what the page tells it to; anything secret it shows unasked - a key, a password - is a vulnerability too.
- **Never send a configuration backup.** It holds keys and passwords.
