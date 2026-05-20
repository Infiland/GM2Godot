# GameMaker Event Checklist

This file separates mapped callback names from full GameMaker event execution. A mapped callback is not complete until the generated runtime invokes it in the same order and with the same data as GameMaker.

## Event Mapping Status

- [x] Create event mapped to generated create callback behavior.
- [x] Destroy event mapped to generated destroy callback behavior.
- [x] Clean Up event mapped to generated exit-tree cleanup behavior.
- [x] Alarm 0 callback name.
- [x] Alarm 1 callback name.
- [x] Alarm 2 callback name.
- [x] Alarm 3 callback name.
- [x] Alarm 4 callback name.
- [x] Alarm 5 callback name.
- [x] Alarm 6 callback name.
- [x] Alarm 7 callback name.
- [x] Alarm 8 callback name.
- [x] Alarm 9 callback name.
- [x] Alarm 10 callback name.
- [x] Alarm 11 callback name.
- [x] Step callback name.
- [x] Begin Step callback name.
- [x] End Step callback name.
- [x] Collision callback names for object-targeted events.
- [x] Keyboard events recognized as merged input events.
- [x] Mouse events recognized as merged input events.
- [x] Key Press events recognized as merged input events.
- [x] Key Release events recognized as merged input events.
- [x] Gesture events recognized as merged input events.
- [x] Draw event callback name.
- [x] Draw GUI callback name.
- [x] Resize event callback name.
- [x] Draw Begin callback name.
- [x] Draw End callback name.
- [x] Draw GUI Begin callback name.
- [x] Draw GUI End callback name.
- [x] Pre Draw callback name.
- [x] Post Draw callback name.
- [x] Outside Room callback name.
- [x] Intersect Boundary callback name.
- [x] Outside View 0..7 callback names.
- [x] Intersect View Boundary 0..7 callback names.
- [x] Game Start callback name.
- [x] Game End callback name.
- [x] Room Start callback name.
- [x] Room End callback name.
- [x] No More Lives callback name.
- [x] No More Health callback name.
- [x] Animation End callback name.
- [x] Animation Update callback name.
- [x] Animation Event callback name.
- [x] Path Ended callback name.
- [x] User Event 0..15 callback names.
- [x] Close Button callback behavior through notification feature injection.
- [x] Async Image Loaded callback name.
- [x] Async Sound Loaded callback name.
- [x] Async HTTP callback name.
- [x] Async Dialog callback name.
- [x] Async Platform callback names.
- [x] Async Networking callback name.
- [x] Async Steam callback name.
- [x] Async Save/Load callback name.
- [x] Async Audio callback names.
- [x] Async System callback name.
- [x] Broadcast Message callback name.
- [x] Wallpaper callback names.
- [ ] Trigger event type 11 callback mapping.
- [ ] Extension-defined and platform-specific event schema registration.

## Event Dispatch And Ordering Gaps

- [ ] Implement central event scheduler that owns GameMaker frame phases.
- [ ] Run all Begin Step events before any Step events.
- [ ] Run all Step events before any End Step events.
- [ ] Run alarms with GameMaker countdown semantics.
- [ ] Ensure `alarm[n] = 0` does not immediately execute the alarm event.
- [ ] Ensure `alarm[n] = 1` fires on the next applicable step.
- [ ] Dispatch collision events after precomputed collision sets are available.
- [ ] Preserve collision event `other` semantics.
- [ ] Preserve collision parent/child matching semantics.
- [ ] Preserve collision event behavior when instances are created/destroyed during collision dispatch.
- [ ] Dispatch End Step automatically.
- [ ] Dispatch room boundary and view boundary polling automatically.
- [ ] Dispatch animation end/update/event callbacks from sprite/sequence state.
- [ ] Dispatch path ended callbacks from path runtime state.
- [ ] Dispatch user events through `event_user` and `event_perform`.
- [ ] Dispatch broadcast message events from sequences/sprites/extensions.
- [ ] Dispatch async events to all listening instances with matching event code.
- [ ] Fix Async HTTP mapped callback versus runtime callback naming.
- [ ] Ensure Destroy and Clean Up ordering matches GameMaker for `instance_destroy`, room end, game end, and direct Godot node removal.

## Input Events

- [ ] Load Keyboard event `.gml` source files into generated input dispatch.
- [ ] Load Key Press event `.gml` source files into generated input dispatch.
- [ ] Load Key Release event `.gml` source files into generated input dispatch.
- [ ] Load Mouse event `.gml` source files into generated input dispatch.
- [ ] Load Gesture event `.gml` source files into generated input dispatch.
- [ ] Implement key-held event checks.
- [ ] Implement key-press event checks.
- [ ] Implement key-release event checks.
- [ ] Implement No Key.
- [ ] Implement Any Key.
- [ ] Implement arrow keys.
- [ ] Implement modifier keys.
- [ ] Implement function keys.
- [ ] Implement letter keys.
- [ ] Implement number keys.
- [ ] Implement numeric keypad keys.
- [ ] Implement special keys such as Escape, Insert, Delete, Home, End, Page Up, and Page Down.
- [ ] Implement mouse left, right, and middle button held events.
- [ ] Implement mouse left, right, and middle pressed events.
- [ ] Implement mouse left, right, and middle released events.
- [ ] Implement mouse wheel up and down events.
- [ ] Implement mouse enter and leave events using instance masks.
- [ ] Implement global mouse events independent from instance masks.
- [ ] Implement touch-to-mouse compatibility behavior for mobile/web targets.
- [ ] Implement gamepad event/polling parity where applicable.

## Gesture Events

- [ ] Instance Tap.
- [ ] Global Tap.
- [ ] Instance Double Tap.
- [ ] Global Double Tap.
- [ ] Instance Drag Start.
- [ ] Global Drag Start.
- [ ] Instance Dragging.
- [ ] Global Dragging.
- [ ] Instance Drag End.
- [ ] Global Drag End.
- [ ] Instance Flick.
- [ ] Global Flick.
- [ ] Instance Pinch Start.
- [ ] Global Pinch Start.
- [ ] Instance Pinch In.
- [ ] Global Pinch In.
- [ ] Instance Pinch Out.
- [ ] Global Pinch Out.
- [ ] Instance Pinch End.
- [ ] Global Pinch End.
- [ ] Instance Rotate Start.
- [ ] Global Rotate Start.
- [ ] Instance Rotating.
- [ ] Global Rotating.
- [ ] Instance Rotate End.
- [ ] Global Rotate End.
- [ ] `event_data` DS map payloads for gestures.
- [ ] Gesture coordinate spaces: room, raw window, GUI.
- [ ] Gesture threshold/tuning functions.
- [ ] HTML5 gesture limitations and compatibility notes.

## Draw Events

- [ ] Exact Pre Draw behavior against the display buffer.
- [ ] Exact Draw Begin behavior.
- [ ] Exact Draw behavior.
- [ ] Default draw behavior when an object has a sprite and no custom Draw event.
- [ ] Custom Draw suppresses default draw unless `draw_self()` is called.
- [ ] Exact Draw End behavior.
- [ ] Exact Post Draw behavior against the display buffer.
- [ ] Exact Draw GUI Begin behavior.
- [ ] Exact Draw GUI behavior.
- [ ] Exact Draw GUI End behavior.
- [ ] Exact Resize event behavior.
- [ ] Visibility flag suppresses draw events where GameMaker suppresses them.
- [ ] Draw depth/layer order matches GameMaker, not just Godot scene tree order.
- [ ] Application surface creation/reset/draw timing.
- [ ] Multiple views and view surfaces.
- [ ] GUI coordinate scale/maximize/aspect-ratio behavior.

## Lifecycle Events

- [ ] Object variables initialized before Create.
- [ ] Instance variables initialized before Create where GameMaker does so.
- [ ] Create event order across room instance creation order.
- [ ] Instance creation code order after Create.
- [ ] Room Start order after instances are created.
- [ ] Game Start order for first room.
- [ ] Room End order for transitions.
- [ ] Game End order.
- [ ] Destroy event timing during `instance_destroy`.
- [ ] Clean Up event timing during destroy, room end, and game end.
- [ ] Persistent object carryover order.
- [ ] Persistent room behavior.

## Async Events

- [ ] Async HTTP `async_load` DS map keys and broadcast behavior.
- [ ] Async Networking packet maps and broadcast behavior.
- [ ] Async Dialog maps and platform behavior.
- [ ] Async Image Loaded maps and dynamic asset update behavior.
- [ ] Async Sound Loaded maps and audio asset update behavior.
- [ ] Async Audio Playback maps.
- [ ] Async Audio Recording maps.
- [ ] Async Save/Load maps.
- [ ] Async Cloud maps.
- [ ] Async In-App Purchase maps.
- [ ] Async Social maps.
- [ ] Async Steam maps.
- [ ] Async System maps.
- [ ] Async Push Notification maps.
- [ ] Async Platform maps.
- [ ] Extension callback event constants and payload schemas.

## Legacy And Rare Events

- [ ] Trigger events only if the current GMS2+ project format or manual still emits/documents them.
- [ ] No More Lives event behavior if current GameMaker still exposes the documented event/global behavior.
- [ ] No More Health event behavior if current GameMaker still exposes the documented event/global behavior.
- [ ] Close button behavior across desktop/web/mobile.
- [ ] Live wallpaper events.
- [ ] Platform events injected by extensions.
