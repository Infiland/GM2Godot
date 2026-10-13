# instance_change(obj, perf): the calling instance becomes an instance of
# another object, as instance_change_RELEASE in the HTML5 runner
# (functions/Function_Instance.js) does it. With perf the instance first runs
# its Destroy and Clean Up events. It then takes the new object's events,
# object_index and parents (its place in the objects' instance lists), mask,
# solid, visible and persistent flags (SetObjectIndex in yyInstance.js) and
# the object's sprite (UpdateSpriteIndex), and keeps its id, its variables, its
# position, depth, image values, motion, alarms and xstart/ystart. With perf
# the new object's Pre-Create and Create events run last, with the instance
# as self and other. Changing to an object that does not exist only prints
# the runner's error (instance_change_DEBUG).
#
# A converted object's events are the methods of its node's script, so the
# change gives the node the new object's script. Godot frees the script
# instance of a node whose script is replaced, and a method of the old script
# that is still running would go on using it; so the node's script changes
# once the instance's running event has returned to the runtime: right after
# its Create event and creation code, after each event of the step, input and
# collision dispatch, and at every step phase boundary. Until then the rest of
# the event that called instance_change still sees the old object.
#
# The instance's later instance_change and instance_destroy calls in that
# event wait with it, in the order they were made, because GameMaker would
# run them on the new object: a second change runs the object it changed into
# first's Destroy and Clean Up (perf), and instance_destroy runs its Destroy
# event, once the first change (and its Create event) is done. Until then the
# instance still exists.

# Script members that the new object sets (or that only cache state of the
# old script) rather than carrying over.
const GML_INSTANCE_CHANGE_OBJECT_MEMBERS = [
	"object_index", "solid", "persistent", "mask_index", "sprite_index", "image_number", "depth",
	"_gm_collision_state", "_gm_collision_dirty", "_gm_sprite_visual_cache",
]
# The image values a room-placed instance takes from its node's metadata when
# its _ready sets it up.
const GML_INSTANCE_CHANGE_IMAGE_METAS = {
	"gamemaker_image_index": "image_index",
	"gamemaker_image_speed": "image_speed",
	"gamemaker_image_angle": "image_angle",
	"gamemaker_image_xscale": "image_xscale",
	"gamemaker_image_yscale": "image_yscale",
	"gamemaker_image_blend": "image_blend",
	"gamemaker_image_alpha": "image_alpha",
}

# Pending operations by node instance id: {"node": the node, "ops": the
# changes ({"kind": "change", "object": object asset entry, "perf": bool,
# "events_done": whether the Destroy and Clean Up events of perf already ran})
# and destroys ({"kind": "destroy"}) in the order the game asked for them}.
static var _gml_instance_changes = {}
# [script, sprite name, visible] of each object's scene, or null, by object
# name.
static var _gml_instance_change_objects = {}
# The instance whose _gm_register_instance runs for a change: its registry
# entry takes the object and parents that gml_instance_register is given.
static var _gml_instance_change_registering = null


static func gml_instance_change(object_selector, perf, inst = null):
	var entry: Variant = _gml_instance_entry(inst)
	if entry == null or entry["destroyed"] or not (inst is Node):
		return gml_undefined()
	var object_entry: Variant = _gml_object_asset_entry(object_selector)
	if object_entry == null:
		print("Error: Trying to change an instance to an nonexistent object type.")
		return gml_undefined()
	if _gml_instance_change_object(object_entry) == null:
		return gml_error("instance_change: object '%s' has no converted scene to change into" % str(object_entry["name"]))
	var perform = gml_bool(perf)
	var pending = _gml_instance_changes.get(inst.get_instance_id())
	if pending != null:
		# The node still runs the first object; the Destroy and Clean Up events
		# are those of the object the instance will have changed into.
		if not _gml_instance_change_destroy_pending(pending):
			pending["ops"].append({"kind": "change", "object": object_entry, "perf": perform, "events_done": false})
		return gml_undefined()
	if perform:
		_gml_instance_change_destroy_events(inst)
	_gml_instance_changes[inst.get_instance_id()] = {
		"node": inst,
		"ops": [{"kind": "change", "object": object_entry, "perf": perform, "events_done": true}],
	}
	return gml_undefined()


# instance_destroy of an instance with a pending change: the instance is
# destroyed once the change is done, as the object it changed into. Returns
# whether the destroy waits.
static func _gml_instance_change_defer_destroy(inst):
	if _gml_instance_changes.is_empty() or typeof(inst) != TYPE_OBJECT or not is_instance_valid(inst):
		return false
	var pending = _gml_instance_changes.get(inst.get_instance_id())
	if pending == null:
		return false
	if not _gml_instance_change_destroy_pending(pending):
		pending["ops"].append({"kind": "destroy"})
	return true


static func _gml_instance_change_destroy_pending(pending):
	var ops = pending["ops"]
	return not ops.is_empty() and ops[ops.size() - 1]["kind"] == "destroy"


# Carries out every pending change. Only for points where no event runs
# (between two events of the step, input and collision dispatch, and at step
# phase boundaries); the Create events it runs may ask for more changes.
static func _gml_instance_change_flush():
	while not _gml_instance_changes.is_empty():
		_gml_instance_change_run(_gml_instance_changes.keys()[0])


# Carries out an instance's pending change once its own Create event and
# creation code have returned (other instances may still be running events).
static func _gml_instance_change_flush_instance(inst):
	if _gml_instance_changes.is_empty() or typeof(inst) != TYPE_OBJECT or not is_instance_valid(inst):
		return
	var key = inst.get_instance_id()
	while _gml_instance_changes.has(key):
		_gml_instance_change_run(key)


# Runs an instance's pending operations in order. An event they run may ask
# for another change, which waits for that event to return: the operations
# left then wait after it.
static func _gml_instance_change_run(key):
	var pending = _gml_instance_changes[key]
	_gml_instance_changes.erase(key)
	var inst = pending["node"]
	var ops = pending["ops"]
	for index in range(ops.size()):
		if not is_instance_valid(inst) or inst.is_queued_for_deletion():
			return
		var entry: Variant = _gml_instance_entry(inst)
		if entry == null or entry["destroyed"]:
			return
		var op = ops[index]
		if op["kind"] == "destroy":
			gml_instance_destroy(inst)
			return
		_gml_instance_change_apply(inst, entry, op)
		var again = _gml_instance_changes.get(key)
		if again != null:
			for rest in ops.slice(index + 1):
				if rest["kind"] == "destroy":
					_gml_instance_change_defer_destroy(inst)
				elif not _gml_instance_change_destroy_pending(again):
					rest["events_done"] = false
					again["ops"].append(rest)
			return


# Destroy and Clean Up events of perf.
static func _gml_instance_change_destroy_events(inst):
	if not _gml_event_scheduler_event_blocked(inst, true):
		_gml_instance_change_event(inst, "_on_destroy")
	if is_instance_valid(inst):
		_gml_instance_change_clean_up(inst)


static func _gml_instance_change_apply(inst, entry, op):
	var object_entry = op["object"]
	var info = _gml_instance_change_object(object_entry)
	if info == null:
		return
	if op["perf"] and not op["events_done"]:
		_gml_instance_change_destroy_events(inst)
		if not is_instance_valid(inst) or inst.is_queued_for_deletion() or entry["destroyed"]:
			return
	var values = _gml_instance_change_member_values(inst)
	var old_visual = inst.call("_gm_current_sprite_scene_root") if inst.has_method("_gm_current_sprite_scene_root") else null
	_gml_instance_change_show_sprite(inst)
	inst.set_script(info[0])
	_gml_instance_change_restore(inst, values)
	_gml_instance_change_identity(inst, entry, object_entry)
	# The object's visible flag (the root node's visible in its scene).
	if inst is CanvasItem:
		inst.visible = info[2]
	if values.has("_gm_depth") and "_gm_depth" in inst:
		# The depth stays (SetObjectIndex leaves it).
		inst.set("_gm_depth", values["_gm_depth"])
	var sprite = gml_sprite_reference(info[1]) if info[1] != "" else -1
	if "sprite_index" in inst:
		inst.set("sprite_index", sprite)
	elif old_visual is Node and is_instance_valid(old_visual) and old_visual.get_parent() == inst:
		inst.remove_child(old_visual)
		old_visual.queue_free()
	# The step list keeps each instance's script info; the input event table
	# is built from the scripts.
	for i in range(_gml_step_entries.size()):
		if is_same(_gml_step_entries[i], entry):
			_gml_step_infos[i] = _gml_step_script_info(inst)
	_gml_input_live_table_mark = -1
	if op["perf"]:
		_gml_instance_change_create(inst)


# The new object's object_index, parents, solid and persistent flags and
# mask, as its _gm_register_instance sets them up for a new instance.
static func _gml_instance_change_identity(inst, entry, object_entry):
	if inst.has_meta("gamemaker_instance_object_name"):
		inst.set_meta("gamemaker_instance_object_name", str(object_entry["name"]))
	if not inst.has_method("_gm_register_instance"):
		_gml_instance_change_reindex(entry, str(object_entry["name"]), [])
		gml_struct_set(inst, "object_index", int(object_entry["id"]))
		return
	var handle = inst.get("id")
	inst.set("id", gml_instance_noone())
	_gml_instance_change_registering = inst
	inst.call("_gm_register_instance")
	_gml_instance_change_registering = null
	inst.set("id", handle)


# Moves a registry entry to another object (with its parents) in the
# instance lists, which stay in creation order, and in the collision
# registry.
static func _gml_instance_change_reindex(entry, object_selector, parent_selectors):
	var inst = entry["instance"]
	_gml_collision_forget_box_lists(entry)
	for selector_id in entry["selector_ids"]:
		_gml_instance_index_remove(_gml_instance_live_by_object, selector_id, entry)
	for selector_name in entry["selector_names"]:
		_gml_instance_index_remove(_gml_instance_live_by_object_name, selector_name, entry)
	entry["object_id"] = _gml_object_selector_id(object_selector)
	entry["object_name"] = _gml_object_selector_name(object_selector)
	entry["selector_ids"] = _gml_object_selector_id_array([object_selector] + parent_selectors)
	entry["selector_names"] = _gml_object_selector_name_array([object_selector] + parent_selectors)
	entry["handle"].name = entry["object_name"]
	for selector_id in entry["selector_ids"]:
		_gml_instance_change_index_insert(_gml_instance_live_by_object, selector_id, entry)
	for selector_name in entry["selector_names"]:
		_gml_instance_change_index_insert(_gml_instance_live_by_object_name, selector_name, entry)
	_gml_collision_forget_box_lists(entry)
	var chain = _gml_collision_entry_object_chain(entry)
	var kept_chain = entry.get("collision_chain")
	if kept_chain is Array:
		# The step's collision dispatch may hold this array.
		kept_chain.clear()
		kept_chain.append_array(chain)
	entry["collision_tracked"] = _gml_collision_tracks(inst)
	if entry["collision_tracked"]:
		inst.set_notify_local_transform(true)
	_gml_collision_register_instance_events(inst, chain)


static func _gml_instance_change_index_insert(index_map, selector, entry):
	# _gml_instance_index_add, keeping the list in creation order.
	if selector == null:
		return
	if is_numeric(selector) and _to_int64_value(selector) == -1:
		return
	if is_string(selector) and str(selector) == "":
		return
	if not index_map.has(selector):
		index_map[selector] = []
	var entries = index_map[selector]
	var order = int(entry["creation_order"])
	var low = 0
	var high = entries.size()
	while low < high:
		var middle = (low + high) >> 1
		if int(entries[middle]["creation_order"]) < order:
			low = middle + 1
		else:
			high = middle
	entries.insert(low, entry)


static func _gml_instance_change_member_values(inst):
	var values = {}
	for property in inst.get_property_list():
		if int(property["usage"]) & PROPERTY_USAGE_SCRIPT_VARIABLE:
			var name = str(property["name"])
			values[name] = inst.get(name)
	return values


# Gives the new script the instance's variables: those it declares as
# members, the rest as the instance's own variables (as GML variables the
# script does not declare are kept).
static func _gml_instance_change_restore(inst, values):
	var declared = {}
	for property in inst.get_property_list():
		if int(property["usage"]) & PROPERTY_USAGE_SCRIPT_VARIABLE:
			declared[str(property["name"])] = true
	var fields = _gml_object_dynamic_fields(inst)
	for name in fields.keys():
		if declared.has(name):
			inst.set(name, fields[name])
			fields.erase(name)
	for name in values:
		if GML_INSTANCE_CHANGE_OBJECT_MEMBERS.has(name):
			continue
		if declared.has(name):
			inst.set(name, values[name])
		elif not str(name).begins_with("_gm_"):
			_gml_object_dynamic_fields(inst, true)[name] = values[name]


# The new object's Pre-Create and Create events. The generated _ready sets
# up a new instance before its Create event: _gm_initialize_motion_runtime
# sets xstart, ystart, xprevious and yprevious to the position, and
# _gm_initialize_sprite_runtime takes the image values of a room-placed
# instance from its metadata and otherwise reads image_angle and the scales
# back from the node's transform. The instance keeps its values instead: the
# metadata holds them, and a value that the set-up gave and the Create event
# left alone goes back to what it was.
static func _gml_instance_change_create(inst):
	var kept = {}
	for meta_name in GML_INSTANCE_CHANGE_IMAGE_METAS:
		var member = GML_INSTANCE_CHANGE_IMAGE_METAS[meta_name]
		if inst.has_meta(meta_name) and member in inst:
			inst.set_meta(meta_name, inst.get(member))
	if inst is Node2D:
		var set_up = {
			"xstart": inst.position.x,
			"ystart": inst.position.y,
			"xprevious": inst.position.x,
			"yprevious": inst.position.y,
			"image_angle": 0.0 - inst.rotation_degrees,
			"image_xscale": inst.scale.x,
			"image_yscale": inst.scale.y,
		}
		for member in set_up:
			if member in inst and not inst.has_meta("gamemaker_" + member):
				kept[member] = [set_up[member], inst.get(member)]
	if inst.has_method("_gm_variable_definitions") and not gml_event_create_blocked(inst):
		# The object's Variable Definitions, where the converter generates them.
		_gml_instance_change_event(inst, "_gm_variable_definitions")
	_gml_instance_change_event(inst, "_ready")
	if not is_instance_valid(inst):
		return
	for member in kept:
		if typeof(inst.get(member)) == typeof(kept[member][0]) and inst.get(member) == kept[member][0]:
			inst.set(member, kept[member][1])


# Runs one of the instance's events with the instance as self and other.
static func _gml_instance_change_event(inst, method_name):
	if not inst.has_method(method_name):
		return
	var has_other = "other" in inst
	var previous_other = inst.get("other") if has_other else null
	if has_other:
		inst.set("other", inst)
	inst.call(method_name)
	if has_other and is_instance_valid(inst):
		inst.set("other", previous_other)


static func _gml_instance_change_clean_up(inst):
	# The Clean Up event is the object's _exit_tree, which also unregisters
	# the instance unless the instance is only leaving the tree for a while;
	# here it stays registered.
	if not inst.has_method("_exit_tree"):
		return
	var preserving = inst.get_meta("_gm2godot_room_preserving_persistent", false)
	inst.set_meta("_gm2godot_room_preserving_persistent", true)
	_gml_instance_change_event(inst, "_exit_tree")
	if is_instance_valid(inst):
		inst.set_meta("_gm2godot_room_preserving_persistent", preserving)


# The draw pipeline hides the sprite node of an instance with a Draw event; a
# new object without one draws its sprite.
static func _gml_instance_change_show_sprite(inst):
	var instance_id = inst.get_instance_id()
	var cached = _gml_draw_hidden_visuals.get(instance_id, null)
	if cached is WeakRef:
		var visual = cached.get_ref()
		if visual is CanvasItem:
			visual.visible = true
	_gml_draw_hidden_visuals.erase(instance_id)


# The script, sprite and visible flag of an object's converted scene.
static func _gml_instance_change_object(object_entry):
	var object_name = str(object_entry["name"])
	if _gml_instance_change_objects.has(object_name):
		return _gml_instance_change_objects[object_name]
	var info = null
	var path = str(object_entry.get("godot_path", ""))
	var scene = load(path) if path != "" and ResourceLoader.exists(path) else null
	if scene is PackedScene:
		var state = scene.get_state()
		var script = null
		var visible = true
		for i in range(state.get_node_property_count(0)):
			if state.get_node_property_name(0, i) == &"script":
				script = state.get_node_property_value(0, i)
			elif state.get_node_property_name(0, i) == &"visible":
				visible = bool(state.get_node_property_value(0, i))
		if script is Script:
			info = [script, _gml_instance_change_scene_sprite(state), visible]
	_gml_instance_change_objects[object_name] = info
	return info


static func _gml_instance_change_scene_sprite(state):
	# An object's scene holds its sprite's scene as a child named after the
	# sprite.
	_gml_asset_registry_ensure_loaded()
	for node_index in range(1, state.get_node_count()):
		if state.get_node_path(node_index, true) != NodePath("."):
			continue
		var node_name = str(state.get_node_name(node_index))
		var asset: Variant = _gml_asset_resolve(node_name)
		if typeof(asset) == TYPE_DICTIONARY and str(asset.get("type", "")) == "sprite":
			return node_name
	return ""
