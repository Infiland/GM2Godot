// Fixture: data structures with text, INI, and JSON save paths.
var inventory = ds_list_create();
ds_list_add(inventory, "key");

var save_map = ds_map_create();
ds_map_set(save_map, "inventory", inventory);
ds_map_set(save_map, "room", room_get_name(room));

var grid = ds_grid_create(2, 2);
ds_grid_set(grid, 0, 0, 42);

var file = file_text_open_write("save/profile.txt");
file_text_write_string(file, json_encode(save_map));
file_text_close(file);

ini_open("save/settings.ini");
ini_write_string("audio", "device", "default");
ini_write_real("audio", "volume", 0.75);
ini_close();
