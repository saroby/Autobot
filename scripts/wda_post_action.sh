#!/usr/bin/env bash
# WDA build post-action for the isolated clone workspace.
#
# Some local WebDriverAgent packages add an icon to the generated Runner.app
# after Xcode signs it. That mutation requires a second codesign operation and
# can fail when the keychain contains duplicate display names for a development
# certificate. The icon is not needed for automation, so leave the signed
# bundle untouched and let Xcode install the signature it produced.
set -euo pipefail

echo "INFO: clone WDA post-action left the signed Runner.app unchanged"
