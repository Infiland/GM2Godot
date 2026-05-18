// Fixture: HTTP requests and async save/load event payloads.
var get_id = http_get("http://127.0.0.1:8000/ping");
var post_id = http_post_string("http://127.0.0.1:8000/post", "score=12");
var put_id = http_request("http://127.0.0.1:8000/put", "PUT", ["X-Fixture: part2"], "payload");

var buffer = buffer_create(16, buffer_grow, 1);
buffer_write(buffer, buffer_string, "save");
var save_id = buffer_save_async(buffer, "save/async.bin");

global.fixture_async_ids = [get_id, post_id, put_id, save_id];

// Async HTTP event.
array_push(global.fixture_async_seen, async_load);
