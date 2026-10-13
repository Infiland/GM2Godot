extends Node2D
# A bare GameMaker instance: the built-in variables collisions and motion read.

var sprite_index = -1
var mask_index = -1
var image_index = 0.0
var image_xscale = 1.0
var image_yscale = 1.0
var image_angle = 0.0
var solid = false
var xprevious = 0.0
var yprevious = 0.0
var direction = 0.0
var speed = 0.0
var hspeed = 0.0
var vspeed = 0.0
var friction = 0.0
var gravity = 0.0
var gravity_direction = 270.0
var other = null
