# Mirai plugins

The catalog of plugins for the [Mirai](https://github.com/mirai-engine) engine. The engine lists
it with `mirai plugin catalog` and in the Plugins page of the project settings, and installs an
entry with `mirai plugin add <name>`, always at the commit the entry pins.

## Adding a plugin

Open a pull request that adds one file, `plugins/<name>.json`, and touches nothing else, so two
additions never conflict:

```json
{
  "description": "Procedural rivers that carve the terrain and flow downhill",
  "url": "https://github.com/someone/mirai-rivers.git",
  "commit": "0123456789abcdef0123456789abcdef01234567"
}
```

- `<name>` is the name in the plugin's `plugin.mirai`: lowercase letters, digits and `_` after a
  letter. No other entry, nor any plugin another repository brings, may use it.
- `url` is the https address of a public git repository with `plugin.mirai` at its root and a
  license file. Plugins in its `plugins/<name>/` folders (bridges to other plugins) install with
  it and need no entry of their own.
- `commit` is the full hash of the commit to review; installs and updates check out exactly that.
- Optionally, add `plugins/<name>.png` in the same pull request: the icon the engine shows for the
  plugin before it is installed, a PNG of at most 128x128 pixels.

The license is the one in the plugin's repository; a plugin carries its data and their licenses
inside it.

To publish a new version, open a pull request that changes the `commit` of your entry. CI runs
`uv run scripts/validate.py`, which you can also run locally before opening the pull request.
