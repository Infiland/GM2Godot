function scr_stats(a, b = 4) {
    var values = [a];
    array_push(values, min(4, 1, 2), max(4, 1, 2), choose(7, 8, 9));
    return values[0] + values[1] + values[2] + b;
}
