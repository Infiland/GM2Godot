{
  "$GMExtension": "v1",
  "%Name": "ext_analytics",
  "name": "ext_analytics",
  "resourceType": "GMExtension",
  "version": "1.0.0",
  "platforms": ["windows"],
  "macros": [{"name": "ANALYTICS_ENABLED", "value": "1"}],
  "files": [
    {
      "filename": "analytics.dll",
      "platform": "windows",
      "functions": [
        {"name": "analytics_track", "externalName": "AnalyticsTrack", "argCount": 2, "returnType": "double"}
      ]
    }
  ]
}
