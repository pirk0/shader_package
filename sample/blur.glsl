// Пасс blur: фото, размытое гауссом 5×5, — в левый нижний угол буфера A, меньше кадра в DOWNSCALE
// раз. Фото берётся с уровня мип-цепочки по уменьшению буфера: без mipmaps в manifest.json уровня
// нет. Дальше рамки live буфер не пишется, и там его никто не читает (manifest.json).
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 R = iResolution.xy;
    float DS = float(DOWNSCALE);
    if (fragCoord.x > R.x / DS + 1.0 || fragCoord.y > R.y / DS + 1.0) discard;
    vec2 uv = fragCoord * DS / R;
    float lod = log2(DS);
    vec4 acc = vec4(0.0);
    float wsum = 0.0;
    for (int i = -2; i <= 2; i++) {
        for (int j = -2; j <= 2; j++) {
            float w = exp(-0.25 * float(i * i + j * j));
            acc += w * textureLod(iChannel0, uv + vec2(float(i), float(j)) * BLUR * DS / R, lod);
            wsum += w;
        }
    }
    fragColor = acc / wsum;
}
