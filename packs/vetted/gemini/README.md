# Gemini

Google's coding agent is Antigravity CLI (`agy`), which is where a personal
Google account's Gemini runs since June 2026. It is not one of the five
AerieOS ships: this pack brings its program and its adapter (AerieOS's
docs/tool-packs.md, "A coding agent of your own"). Installed from the
Library on a node, Start offers Gemini there like any other agent. It needs
an AerieOS whose pack format knows the `named` hooks shape.

- **The program** is fetched from Google's own storage at the one release
  the pack pins, and held to the sha512 Google's release manifest gave for
  it. A newer release is a new pin in the catalog, vetted and signed; the
  copy a session runs is the node's, which a session cannot write, so its
  own background updater changes nothing that runs.
- **The briefing** is put into the conversation as a system message by its
  own hook when a conversation starts, and again on the first prompt after
  a restart changed it. Antigravity CLI has no option for one, and its
  rules file (`~/.gemini/GEMINI.md`) is the person's own, which AerieOS
  leaves alone.
- **The guards** hold through its hooks, in `~/.gemini/config/hooks.json`
  under the name `aerieos`, beside any a person keeps there: before every
  tool, on a prompt and at the stop. It has no hook after a summary and
  none for its permission prompt, so the house rules are not said again
  after one and its dot is never asking.
- **Signing in** is its own: the first session shows its link in the
  terminal, you open it, sign in to Google and paste the code back. The
  Agents page has no card for it. A `GEMINI_API_KEY` in the session's
  environment, with `"modelProvider": "gemini"` in
  `~/.gemini/antigravity-cli/settings.json`, runs it on a key instead.

The adapter was written from Antigravity CLI 1.5.6's documentation, its
install script and its release notes, and its tests hold it to the
payloads those document.
