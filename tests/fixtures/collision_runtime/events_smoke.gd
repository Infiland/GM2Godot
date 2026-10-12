extends Node2D
# Collision events of generated object scripts, checked against the order and
# rules of the GameMaker runner: both instances run their event, parent and
# inherited events, same-object pairs, solid instances, destroyed and newly
# created instances, instances without a mask and restoring other.

const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

var entries = []
var _failures = []
var _spawned = []


func _expect(label, actual, expected):
	if typeof(actual) in [TYPE_INT, TYPE_FLOAT] and typeof(expected) in [TYPE_INT, TYPE_FLOAT]:
		if abs(float(actual) - float(expected)) <= 0.0005:
			return
	elif typeof(actual) == typeof(expected) and actual == expected:
		return
	_failures.append("%s: expected %s, got %s" % [label, str(expected), str(actual)])


# Called by the generated collision events.
func record(tag, inst, other):
	var other_label = str(other.label) if other is Object and "label" in other else str(other)
	var other_x = int(round(other.position.x)) if other is Node2D else -1
	entries.append("%s:%s<-%s@%d" % [tag, str(inst.label), other_label, other_x])


func spawn(object_name, label, x, y):
	var node = Node2D.new()
	node.set_script(load("res://objects/%s/%s.gd" % [object_name, object_name]))
	node.label = label
	node.position = Vector2(x, y)
	add_child(node)
	_spawned.append(node)
	return node


func _dispatch():
	entries.clear()
	GMRuntime.gml_collision_event_dispatch_frame()
	return entries.duplicate()


func _clear():
	for node in _spawned:
		if is_instance_valid(node):
			GMRuntime.gml_instance_destroy(node)
	_spawned.clear()


func _ready():
	call_deferred("_run")


func _run():
	_expect("project setting turns on compatibility mode", GMRuntime._gml_collision_compatibility(), true)
	_case_mutual()
	_case_parent_target()
	_case_inherited_event()
	_case_same_object()
	_case_solid(true)
	_case_solid(false)
	_case_solid_changed_by_event()
	_case_destroyed()
	_case_queued_for_deletion()
	_case_step_phase()
	_case_spawned()
	_case_spriteless()
	_case_other_restored()
	_case_trace()
	_case_registry_replaced()
	_case_room_change()
	if _failures.is_empty():
		print("COLLISION_EVENTS_OK")
		get_tree().quit(0)
		return
	for failure in _failures:
		print("FAIL " + failure)
	get_tree().quit(1)


func _case_mutual():
	spawn("o_b", "b", 8, 0)
	spawn("o_a", "a", 0, 0)
	_expect("mutual events run once each, first object first", _dispatch(), ["a:b:a<-b@8", "b:a:b<-a@0"])
	_clear()


func _case_parent_target():
	spawn("o_a", "a", 0, 0)
	spawn("o_child", "child", 8, 0)
	_expect("event for a parent object matches its children", _dispatch(), ["a:par:a<-child@8", "child:a:child<-a@0"])
	_clear()


func _case_inherited_event():
	spawn("o_child", "child", 100, 0)
	spawn("o_c", "c", 108, 0)
	_expect("child instances run their parent's event", _dispatch(), ["par:c:child<-c@108"])
	_clear()


func _case_same_object():
	spawn("o_same", "s1", 200, 0)
	spawn("o_same", "s2", 208, 0)
	spawn("o_same", "s3", 216, 0)
	_expect("same-object pairs run once per pair", _dispatch(), [
		"same:s1<-s2@208", "same:s2<-s1@200", "same:s2<-s3@216", "same:s3<-s2@208",
	])
	_clear()


func _case_solid(compat):
	GMRuntime._gml_collision_set_compatibility_mode(compat)
	var wall = spawn("o_wall", "wall", 300, 0)
	var mover = spawn("o_a", "mover", 310, 0)
	mover.xprevious = 330.0
	mover.hspeed = -5.0
	var mode = "compat" if compat else "exact"
	_expect(mode + " generated object is solid", wall.solid, true)
	_expect(mode + " solid collision moves back before the events", _dispatch(), ["wall:a:wall<-mover@330"])
	_expect(mode + " mover position after solid collision", mover.position.x, 325.0 if compat else 330.0)
	_expect(mode + " wall stays", wall.position.x, 300.0)
	mover.position = Vector2(310, 0)
	mover.hspeed = -20.0
	_dispatch()
	_expect(mode + " mover moved back again when the retry still collides", mover.position.x, 330.0)
	_clear()
	GMRuntime._gml_collision_set_compatibility_mode(null)


# In compatibility mode the retry after both events reads solid again, and an
# instance destroyed by an event no longer collides (HTML5 runner,
# Events.js HandleCollision and yyInstance.js Collision_Instance).
func _case_solid_changed_by_event():
	GMRuntime._gml_collision_set_compatibility_mode(true)
	spawn("o_wall", "vanishing", 1200, 0)
	var mover = spawn("o_a", "mover", 1210, 0)
	mover.xprevious = 1230.0
	mover.hspeed = -20.0
	_expect("vanishing wall runs its event", _dispatch(), ["wall:a:vanishing<-mover@1230"])
	_expect("retry keeps the move once the solid instance is destroyed", mover.position.x, 1210.0)
	_clear()
	var door = spawn("o_wall", "opening", 1300, 0)
	mover = spawn("o_a", "mover", 1310, 0)
	mover.xprevious = 1330.0
	mover.hspeed = -5.0
	_expect("opening door runs its event", _dispatch(), ["wall:a:opening<-mover@1330"])
	_expect("the event made the door non-solid", door.solid, false)
	_expect("no retry once neither instance is solid", mover.position.x, 1330.0)
	_clear()
	GMRuntime._gml_collision_set_compatibility_mode(null)


func _case_destroyed():
	spawn("o_a", "killer", 400, 0)
	spawn("o_b", "b1", 405, 0)
	spawn("o_b", "b2", 410, 0)
	var gone = spawn("o_b", "gone", 400, 0)
	GMRuntime.gml_instance_destroy(gone)
	_expect("destroyed instances stop colliding", _dispatch(), ["a:b:killer<-b1@405", "b:a:b1<-killer@400"])
	_clear()


# A node queued for deletion is leaving the room like a destroyed instance,
# and the step leaves it out of every phase, the collision events included.
func _case_queued_for_deletion():
	spawn("o_a", "a", 1400, 0)
	var leaving = spawn("o_b", "leaving", 1405, 0)
	leaving.queue_free()
	_expect("instances queued for deletion stop colliding", _dispatch(), [])
	_clear()


# A step's collision phase takes in every instance of the step.
func _case_step_phase():
	spawn("o_a", "a", 1500, 0)
	spawn("o_b", "b", 1505, 0)
	entries.clear()
	GMRuntime.gml_event_scheduler_set_enabled(true)
	GMRuntime.gml_event_scheduler_frame(0.0, 1)
	GMRuntime.gml_event_scheduler_set_enabled(false)
	_expect("the step runs the collision events", entries.duplicate(), ["a:b:a<-b@1505", "b:a:b<-a@1500"])
	_clear()


func _case_spawned():
	spawn("o_a", "spawner", 500, 0)
	spawn("o_b", "b", 505, 0)
	_expect("instances created by a collision event wait for the next step", _dispatch(), [
		"a:b:spawner<-b@505", "b:a:b<-spawner@500",
	])
	_expect("next step sees the new instance", _dispatch().size(), 4)
	_clear()


func _case_spriteless():
	var a = spawn("o_a", "a", 600, 0)
	a.sprite_index = -1
	spawn("o_b", "b", 600, 0)
	_expect("instances without a sprite never collide", _dispatch(), [])
	_clear()


func _case_other_restored():
	var a = spawn("o_a", "a", 700, 0)
	spawn("o_b", "b", 708, 0)
	var before = a.other
	_dispatch()
	_expect("other is restored after the event", is_same(a.other, before), true)
	_clear()


func _case_trace():
	GMRuntime.gml_collision_event_trace_clear()
	spawn("o_wall", "wall", 800, 0)
	var mover = spawn("o_a", "mover", 805, 0)
	mover.xprevious = 820.0
	_expect("dispatch reports the events it ran", GMRuntime.gml_collision_event_dispatch_frame(), 1)
	var trace = GMRuntime.gml_collision_event_trace()
	_expect("trace starts with the solid move back", str(trace[0].get("event", "")), "solid_rollback")
	_expect("trace names the collision event", str(trace[-1].get("method", "")), "_on_collision_o_a")
	_clear()


# The collision table follows the object order of the asset registry, also
# after the registry is replaced.
func _case_registry_replaced():
	var original = GMRuntime.gml_asset_registry_entries().duplicate()
	var objects = []
	var others = []
	for entry in original:
		if str(entry.get("type", "")) == "object":
			objects.push_front(entry)
		else:
			others.append(entry)
	GMRuntime.gml_asset_registry_set(others + objects)
	spawn("o_b", "b", 908, 0)
	spawn("o_a", "a", 900, 0)
	_expect("replaced registry reorders the collision table", _dispatch(), ["b:a:b<-a@900", "a:b:a<-b@908"])
	_clear()
	GMRuntime.gml_asset_registry_set(original)


# Once an event asks for a room change (game_end here), the other collision
# events of the step do not run; solid instances still move back.
func _case_room_change():
	GMRuntime.gml_room_set_deferred_changes(true)
	spawn("o_a", "leaver", 1000, 0)
	spawn("o_b", "b1", 1005, 0)
	var wall = spawn("o_wall", "wall", 1100, 0)
	var mover = spawn("o_a", "mover", 1110, 0)
	mover.xprevious = 1130.0
	_expect("a pending room change ends the collision events", _dispatch(), ["a:b:leaver<-b1@1005"])
	_expect("the room change is still pending", GMRuntime.gml_room_change_pending(), true)
	_expect("a solid collision still moves back", mover.position.x, 1130.0)
	_expect("the solid instance stays", wall.position.x, 1100.0)
	GMRuntime.gml_room_set_deferred_changes(false)
	_clear()
