# GameMaker Extension Compatibility

GM2Godot classifies GameMaker extension functions separately from built-in GML APIs and project scripts. Extension functions are discovered from `extensions/<name>/<name>.yy` metadata when a GameMaker project is indexed.

Unmapped extension calls are not emitted as raw GDScript. Native extensions, marketplace SDKs, ad networks, analytics SDKs, Steam/IAP wrappers, and platform services can require closed binaries, platform entitlements, or unsafe native bindings. A converted project must opt in with an explicit local mapping.

## Generated Metadata

Asset registry conversion writes `res://gm2godot/extension_compatibility_report.json`. The report preserves each extension's source path, version, platform/file metadata, constants, macros, options, discovered functions, mapped function names, generated stub paths, and diagnostics for native binaries or unmapped functions.

GM2Godot also writes one disabled-by-default Godot addon stub per extension under `res://addons/gm2godot_extensions/<extension>/`. These stubs make the expected implementation points visible, but they intentionally only call `push_error()` until a project-specific script, addon, or GDExtension implementation replaces them.

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

## Platform Service Hooks

Closed or service-backed GameMaker APIs can be handled by registering a Godot addon, script, or GDExtension hook with the generated runtime:

```gdscript
GMRuntime.gml_platform_service_register("steam", {
    "steam_set_achievement": func(name):
        return {
            "result": true,
            "async_payload": {"achievement": name, "status": 1}
        }
})
```

Hook methods receive the emitted GML arguments in order. A hook may return a raw value, or a dictionary with:

- `result`: the value returned to the converted GML call.
- `async_payload`: a dictionary assigned to `async_load` and dispatched to the default async handler for the service.
- `async_kind` and `handler`: optional overrides for the async event kind and generated handler name.

Default async handlers are `_on_async_steam`, `_on_async_in_app_purchase`, `_on_async_cloud_save`, `_on_async_social`, and `_on_async_push_notification`. Missing hooks call `GMRuntime.gml_platform_service_unsupported(api, service)` so the runtime diagnostic names both the GameMaker API and service family.

## Extension Async Callback Schemas

Project addons can register extension callback payload schemas with the runtime and then dispatch callbacks through the same async queue used by HTTP and platform services:

```gdscript
GMRuntime.gml_extension_async_schema_register("AdSDK", "ads_rewarded", {
    "kind": "ads",
    "handler": "_on_async_ads",
    "fields": {"rewarded": "bool", "placement": "string"}
})

GMRuntime.gml_extension_async_dispatch("AdSDK", "ads_rewarded", {
    "rewarded": true,
    "placement": "main_menu"
})
```

The dispatched `async_load` payload includes `extension`, `callback`, and `schema` keys so generated code and user-authored handlers can validate the callback source and payload shape consistently.
