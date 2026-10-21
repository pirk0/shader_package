// Пасс image: фото; в пятне — размытое фото из буфера A и решётка точек.
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 R = iResolution.xy;
    vec2 uv = fragCoord / R;
    vec3 photo = texture(iChannel0, uv).rgb;
    vec3 inside = photo;
    if (BLUR != 0.0) inside = texture(iChannel1, uv / float(DOWNSCALE)).rgb;  // skip пасса blur
    float r = RADIUS;
#if PULSE_MODE != 0
    r *= 1.0 + 0.2 * sin(iTime * PULSE);                                       // объявление time
#endif
    vec2 p = (fragCoord - SPOT * R) / R.y;
    // решётка nx × ny в пятне; цикл не длиннее MAX_DOTS — предупреждение too_many_dots
    float nx = max(floor(COLS + 0.5), 1.0);
    float ny = max(floor(ROWS + 0.5), 1.0);
    vec2 q = mat2(SPIN.x, -SPIN.y, SPIN.y, SPIN.x) * p / r;
    float dots = 0.0;
    for (int i = 0; i < MAX_DOTS; i++) {
        if (float(i) >= nx * ny) break;
        vec2 cell = vec2(mod(float(i), nx), floor(float(i) / nx));
        vec2 c = ((cell + 0.5) / vec2(nx, ny) * 2.0 - 1.0) * 0.7;
        dots = max(dots, 1.0 - smoothstep(0.07, 0.1, length(q - c)));
    }
    vec3 spot = mix(inside, vec3(1.0), 0.6 * dots);
    fragColor = vec4(mix(photo, spot, EDGE(length(p) - r)), 1.0);
}
