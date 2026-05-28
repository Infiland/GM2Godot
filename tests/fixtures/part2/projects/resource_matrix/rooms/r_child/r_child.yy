{
  "$GMRoom": "v1",
  "%Name": "r_child",
  "name": "r_child",
  "resourceType": "GMRoom",
  "creationCodeFile": "",
  "inheritCode": false,
  "inheritCreationOrder": false,
  "inheritLayers": true,
  "isDnd": false,
  "parent": {"name": "Rooms", "path": "folders/Rooms.yy"},
  "parentRoom": {"name": "r_parent", "path": "rooms/r_parent/r_parent.yy"},
  "roomSettings": {"Width": 640, "Height": 360, "persistent": true, "inheritRoomSettings": false},
  "physicsSettings": {"PhysicsWorld": true, "PhysicsWorldGravityX": 0.0, "PhysicsWorldGravityY": 10.0, "PhysicsWorldPixToMetres": 0.1, "inheritPhysicsSettings": true},
  "viewSettings": {"enableViews": true},
  "views": [
    {"visible": true, "xview": 0, "yview": 0, "wview": 320, "hview": 180, "xport": 0, "yport": 0, "wport": 640, "hport": 360},
    {"visible": true, "xview": 320, "yview": 0, "wview": 320, "hview": 180, "xport": 640, "yport": 0, "wport": 640, "hport": 360}
  ],
  "instanceCreationOrder": [
    {"name": "inst_box", "path": "rooms/r_child/r_child.yy"}
  ],
  "layers": [
    {
      "%Name": "ChildInstances",
      "name": "ChildInstances",
      "resourceType": "GMRInstanceLayer",
      "depth": 0,
      "instances": [
        {"name": "inst_box", "objectId": {"name": "o_physics_box", "path": "objects/o_physics_box/o_physics_box.yy"}, "x": 32, "y": 32}
      ]
    },
    {
      "%Name": "GroundTiles",
      "name": "GroundTiles",
      "resourceType": "GMRTileLayer",
      "depth": 100,
      "tilesetId": {"name": "ts_ground", "path": "tilesets/ts_ground/ts_ground.yy"},
      "tiles": {"SerialiseWidth": 2, "SerialiseHeight": 2, "TileDataFormat": 0, "TileCompressedData": [1, 0, 0, 2]}
    },
    {
      "%Name": "FX",
      "name": "FX",
      "resourceType": "GMREffectLayer",
      "effectType": "_filter_colourise",
      "properties": [{"name": "g_TintCol", "type": 1, "value": "16777215"}]
    }
  ],
  "volume": 1.0
}
