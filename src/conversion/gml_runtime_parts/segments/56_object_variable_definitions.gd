# Object Variable Definitions. GameMaker compiles an object's Variable
# Definitions into its Pre-Create event: event_inherited() (the parent's
# definitions), the object's overrides of inherited definitions, then its own
# definitions; generated object scripts hold it as _gm_variable_definitions,
# which a child object without definitions of its own inherits. A
# room-placed instance also has pre-creation code: the values overridden for
# it in the Room Editor, which its room's script holds. Both run once, in
# that order, right before the instance's Create event (or when an object
# without a Create event is created), and like the Create event neither runs
# once a room change is pending, unless the instance or the room is
# persistent (runner: StartRoom in _GameMaker.js, instance_create_depth and
# instance_create_layer in Function_Layers.js, PerformEvent in yyObject.js;
# manual: Object Variables, "Pre-creation Code").
const GML_INSTANCE_PRE_CREATED_META = "_gm2godot_pre_created"


static func gml_instance_pre_create(inst):
	if not (inst is Node) or inst.has_meta(GML_INSTANCE_PRE_CREATED_META):
		return
	inst.set_meta(GML_INSTANCE_PRE_CREATED_META, true)
	if _gml_event_scheduler_event_blocked(inst, true):
		return
	if inst.has_method("_gm_variable_definitions"):
		inst.call("_gm_variable_definitions")
	_gml_instance_room_pre_create(inst)


# A placed instance's room overrides: the first ancestor with the room's
# pre-creation code runs it (it knows the instance by its room name).
static func _gml_instance_room_pre_create(inst):
	if not inst.has_meta("gamemaker_instance_name"):
		return
	var node = inst.get_parent()
	while node != null:
		if node.has_method("_gm2godot_run_instance_pre_create_code"):
			node.call("_gm2godot_run_instance_pre_create_code", inst)
			return
		node = node.get_parent()
