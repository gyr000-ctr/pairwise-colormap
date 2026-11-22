"""colormap 核心 API：色带映射 + 感知均匀插值。

设计要点
--------
- 解析求值在 OKLab 空间进行：
    * 色度 a、b 在相邻停靠点之间直接线性插值；
    * 明度通道以"sRGB 灰阶等效值" g = srgb_encode(L) 为插值参数、线性插值后
      还原回 OKLab 的 L。这样黑白灰带在 t=0.5 处落在 sRGB 0.5（与既有
      行为一致），而彩色色带的过渡路径由 OKLab 决定，与 sRGB 直接插值
      明显可区分（例如红->蓝的中点不是纯 sRGB 中点 (0.5,0,0.5)）。
- 色带量化为 N 级 LUT，查表时在相邻两级之间线性插值：
    * LUT 在各级节点上取解析值，节点处二者完全相等（误差 0）；
    * 查表本身为纯下标 + 一次线性组合，10 万次远低于 100 ms。
- 越界 clamp；非有限输入报错；非单调（OKLab 明度下降）色带报错；
  级数非法报错。LUT 在构造期一次性建好，之后全程只读、查表无共享可变
  状态，因此并发查表安全。
"""

from bisect import bisect_right
from math import cbrt, isfinite, isnan

__all__ = ["ColorMap"]

_MAX_STOPS = 1024          # 停靠点数量上限
_MAX_LEVELS = 1 << 20      # 级数上限
_MONO_TOL = 1e-12          # 单调性容差（吸收浮点往返误差）


def _clamp01(v):
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _srgb_to_linear(c):
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c):
    if c <= 0.0031308:
        return 12.92 * c
    return 1.055 * c ** (1.0 / 2.4) - 0.055


def _srgb_to_oklab(r, g, b):
    """sRGB [0,1] -> OKLab (L, a, b)。"""
    r = _srgb_to_linear(r)
    g = _srgb_to_linear(g)
    b = _srgb_to_linear(b)
    l = cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    )


def _oklab_to_srgb(L, a, b):
    """OKLab (L, a, b) -> sRGB [0,1]，逐通道 clamp。"""
    l = L + 0.3963377774 * a + 0.2158037573 * b
    m = L - 0.1055613458 * a - 0.0638541728 * b
    s = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l * l * l, m * m * m, s * s * s
    r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    b = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return (
        _clamp01(_linear_to_srgb(r)),
        _clamp01(_linear_to_srgb(g)),
        _clamp01(_linear_to_srgb(b)),
    )


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class ColorMap:
    """量化为 N 级的感知均匀色带。"""

    def __init__(self, stops, levels=256):
        """构造：校验级数与停靠点，构建 N 级 LUT。

        stops: [(pos, (r, g, b)), ...]；pos ∈ [0,1] 严格递增，颜色 ∈ [0,1]。
        levels: 整数级数，1 <= levels <= 2**20。
        """
        if isinstance(levels, bool) or not isinstance(levels, int):
            raise ValueError("级数 levels 必须是整数")
        if levels < 1 or levels > _MAX_LEVELS:
            raise ValueError("级数 levels 超出合法范围 [1, 2**20]")

        try:
            raw = list(stops)
        except TypeError as exc:
            raise ValueError("停靠点必须是可迭代的 (pos, (r, g, b)) 序列") from exc
        if not raw:
            raise ValueError("停靠点不能为空")
        if len(raw) > _MAX_STOPS:
            raise ValueError("停靠点数量超过上限 %d" % _MAX_STOPS)

        pos, exact, gs, aa, bb, light = [], [], [], [], [], []
        prev_p = None
        for stop in raw:
            try:
                p, color = stop
                r, g, b = color
                p = float(p)
                r = float(r)
                g = float(g)
                b = float(b)
            except (TypeError, ValueError) as exc:
                raise ValueError("停靠点格式非法，应为 (pos, (r, g, b))") from exc
            if not (isfinite(p) and isfinite(r) and isfinite(g) and isfinite(b)):
                raise ValueError("停靠点含非有限输入")
            if p < 0.0 or p > 1.0:
                raise ValueError("停靠点位置越界，须在 [0, 1] 内")
            if prev_p is not None and p <= prev_p:
                raise ValueError("停靠点位置必须严格递增")
            prev_p = p
            r, g, b = _clamp01(r), _clamp01(g), _clamp01(b)
            L, a, bb2 = _srgb_to_oklab(r, g, b)
            pos.append(p)
            exact.append((r, g, b))
            light.append(L)
            gs.append(_linear_to_srgb(L * L * L))  # 与 L 等效的 sRGB 灰阶值
            aa.append(a)
            bb.append(bb2)

        self._pos = tuple(pos)
        self._exact = tuple(exact)
        self._gs = tuple(gs)
        self._aa = tuple(aa)
        self._bb = tuple(bb)
        self._levels = levels
        # 单调性：OKLab 明度沿色带非递减（段内 L 对 g 单调，逐停靠点检查即精确）
        self._monotonic = all(
            light[i + 1] >= light[i] - _MONO_TOL for i in range(len(light) - 1)
        )
        self._build_lut()

    # ------------------------------------------------------------------ LUT
    def _build_lut(self):
        """构建 N 级 LUT 与相邻差分表；构造后只读。"""
        n = self._levels
        if n == 1:
            c = self._eval(0.0)
            self._r = (c[0],)
            self._g = (c[1],)
            self._b = (c[2],)
            self._dr = self._dg = self._db = (0.0,)
            self._scale = 0.0
        else:
            ev = self._eval
            cols = [ev(i / (n - 1)) for i in range(n)]
            rs = [c[0] for c in cols]
            gs = [c[1] for c in cols]
            bs = [c[2] for c in cols]
            self._r = tuple(rs)
            self._g = tuple(gs)
            self._b = tuple(bs)
            self._dr = tuple(rs[i + 1] - rs[i] for i in range(n - 1)) + (0.0,)
            self._dg = tuple(gs[i + 1] - gs[i] for i in range(n - 1)) + (0.0,)
            self._db = tuple(bs[i + 1] - bs[i] for i in range(n - 1)) + (0.0,)
            self._scale = float(n - 1)
        self._c0 = (self._r[0], self._g[0], self._b[0])
        self._c1 = (self._r[-1], self._g[-1], self._b[-1])

    # --------------------------------------------------------------- eval
    def _eval(self, t):
        """解析求值：t ∈ [0,1] -> (r, g, b)，在 OKLab 空间插值。"""
        pos = self._pos
        if t <= pos[0]:
            return self._exact[0]
        if t >= pos[-1]:
            return self._exact[-1]
        j = bisect_right(pos, t) - 1
        if j >= len(pos) - 1:          # 浮点边界，容错右端
            return self._exact[-1]
        if pos[j] == t:
            return self._exact[j]
        u = (t - pos[j]) / (pos[j + 1] - pos[j])
        g = self._gs[j] + u * (self._gs[j + 1] - self._gs[j])
        a = self._aa[j] + u * (self._aa[j + 1] - self._aa[j])
        b = self._bb[j] + u * (self._bb[j + 1] - self._bb[j])
        L = cbrt(_srgb_to_linear(g))
        return _oklab_to_srgb(L, a, b)

    def analytic(self, t):
        """解析求值入口（便于与 LUT 对照）；同样做越界 clamp 与类型校验。"""
        t = self._check_t(t)
        if t <= 0.0:
            return self._exact[0]
        if t >= 1.0:
            return self._exact[-1]
        return self._eval(t)

    @staticmethod
    def _check_t(t):
        if not _is_number(t):
            raise ValueError("查表参数必须是实数")
        t = float(t)
        if isnan(t):                 # NaN 无法排序/clamp，属非法非有限输入
            raise ValueError("查表参数不能为 NaN")
        return t

    # -------------------------------------------------------------- public
    def lookup(self, t):
        """查表：越界 clamp，非有限输入报错，线程安全。"""
        t = self._check_t(t)
        if t <= 0.0:
            return self._c0
        if t >= 1.0:
            return self._c1
        x = t * self._scale
        i = int(x)
        n = self._levels
        if i >= n - 1:                 # 浮点边界：末级
            return self._c1
        f = x - i
        r = self._r
        g = self._g
        b = self._b
        return (
            r[i] + f * self._dr[i],
            g[i] + f * self._dg[i],
            b[i] + f * self._db[i],
        )

    def validate(self):
        """单调校验：OKLab 明度非递减返回 True，否则抛 ValueError。"""
        if not self._monotonic:
            raise ValueError("非单调色带：OKLab 明度沿色带下降")
        return True

    def to_int8(self, rgb):
        """(r,g,b) ∈ [0,1] -> (0..255, 0..255, 0..255)，四舍五入并 clamp。

        对量化为 N 级的色带，先 lookup 再取其 int8 表示可得到 ≤N 级的离散色带。
        """
        if not all(_is_number(v) for v in rgb):
            raise ValueError("颜色分量必须是实数")
        return tuple(int(_clamp01(float(v)) * 255.0 + 0.5) for v in rgb)

    def levels(self):
        """已量化的级数 N。"""
        return self._levels
