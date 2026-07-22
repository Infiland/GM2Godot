# GameMaker shader corpus

`tcc_wave` and `tcc_grayscale` are preserved from The Colorful Creature at
commit `4b6e942caca4d58af49dc006a037404d2f2a348c`, which is distributed under
Apache-2.0. `standard_color` is a GM2Godot regression pair authored for issue
#708. The manifest records each pair's exact origin and exercised semantics.

These are source `.vsh` + `.fsh` pairs, not expected Godot output. Tests convert
every manifest case and require exact Godot 4.7.1 to load the resulting
`.gdshader`.
