# GameMaker Extension Compatibility

GM2Godot classifies GameMaker extension functions separately from built-in GML APIs and project scripts. Extension functions are discovered from `extensions/<name>/<name>.yy` metadata when a GameMaker project is indexed.

Unmapped extension calls are not emitted as raw GDScript. Native extensions, marketplace SDKs, ad networks, analytics SDKs, Steam/IAP wrappers, and platform services can require closed binaries, platform entitlements, or unsafe native bindings. A converted project must opt in with an explicit local mapping.

## Mapping File

Place `gm2godot_extension_functions.json` in the GameMaker project root:

```json
{
  "functions": {
    "ads_show_rewarded": {
      "target": "AdBridge.show_rewarded",
      "min_args": 1,
      "max_args": 1
    },
    "analytics_event": "AnalyticsBridge.event"
  }
}
```

The `target` value is emitted as a Godot call target. For example, `ads_show_rewarded(zone)` becomes `AdBridge.show_rewarded(zone)`. The target should be backed by a reviewed Godot script, plugin, or GDExtension that handles export-specific permissions and SDK setup.

Keep mappings project-local. GM2Godot does not guess native behavior from extension names.
