extends "res://instance.gd"
# An instance whose object has a collision event with the object "target".

var hits = 0


func _on_collision_target():
	hits += 1
