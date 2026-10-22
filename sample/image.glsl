// Пасс image: фото; в пятне — размытое фото из буфера A под окраской и решётка точек.
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 R = iResolution.xy;
    vec2 uv = fragCoord / R;
    vec3 photo = texture(iChannel0, uv).rgb;
    float r = RADIUS;
#if PULSE_MODE != 0
    r *= 1.0 + 0.2 * sin(iTime * PULSE);                                       // объявление time
#endif
    vec2 p = (fragCoord - SPOT * R) / R.y;
    if (length(p) - r > MARGIN) { fragColor = vec4(photo, 1.0); return; }     // запас MARGIN
    vec3 inside = photo;
    if (BLUR != 0.0) inside = texture(iChannel1, uv / float(DOWNSCALE)).rgb;  // skip пасса blur
    inside *= exp(-TINT);
    // решётка nx × ny в пятне; цикл не длиннее MAX_DOTS — предупреждение too_many_dots
    float nx = max(floor(COLS + 0.5), 1.0);
    float ny = max(floor(ROWS + 0.5), 1.0);
    vec2 q = mat2(SPIN.x, -SPIN.y, SPIN.y, SPIN.x) * p / r;
    vec2 L = vec2(cos(LIGHT), sin(LIGHT));
    float dots = 0.0;
    for (int i = 0; i < MAX_DOTS; i++) {
        if (float(i) >= nx * ny) break;
        vec2 cell = vec2(mod(float(i), nx), floor(float(i) / nx));
        vec2 d = q - ((cell + 0.5) / vec2(nx, ny) * 2.0 - 1.0) * 0.7;
        float lit = clamp(0.5 + 0.5 * dot(d, L) / (DOT.x + DOT.y), 0.0, 1.0);
        dots = max(dots, (1.0 - smoothstep(DOT.x, DOT.x + DOT.y, length(d))) * mix(0.6, 1.0, lit));
    }
    vec3 spot = mix(inside, vec3(1.0), DOT.z * dots);
    fragColor = vec4(mix(photo, spot, EDGE(length(p) - r)), 1.0);
}
