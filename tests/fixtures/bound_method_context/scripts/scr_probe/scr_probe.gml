function scr_probe() {
    var target = {tag: "target"};
    var direct_result = scr_receiver("direct");
    var rebound_script = method(target, scr_receiver);
    var rebound_result = rebound_script("rebound");

    var plain_instance = new scr_constructor(7);
    var constructor_scope = {tag: "constructor-bound"};
    var rebound_constructor = method(constructor_scope, scr_constructor);
    var rebound_instance = new rebound_constructor(9);

    var caller = {tag: "caller"};
    var first = {tag: "first"};
    var second = {tag: "second"};
    var inner = method(second, function() {
        return [self.tag, other.tag];
    });
    var outer = method(first, function(callback) {
        return callback();
    });
    var map_callback = method(second, function(value, index, source) {
        return [self.tag, other.tag, value, index, array_length(source)];
    });
    var foreach_scope = {tag: "foreach", seen: []};
    var foreach_callback = method(foreach_scope, function(value, index) {
        array_push(seen, [self.tag, other.tag, value, index]);
    });
    var invoke = method(caller, function(
        outer_method,
        inner_method,
        callback,
        foreach_method,
        foreach_state
    ) {
        array_foreach([8], foreach_method);
        return [
            outer_method(inner_method),
            method_call(inner_method),
            array_map([7], callback),
            foreach_state.seen
        ];
    });

    return [
        direct_result,
        rebound_result,
        [plain_instance.other_tag, plain_instance.value_seen],
        [rebound_instance.other_tag, rebound_instance.value_seen],
        invoke(
            outer,
            inner,
            map_callback,
            foreach_callback,
            foreach_scope
        )
    ];
}
