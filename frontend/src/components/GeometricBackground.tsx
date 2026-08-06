// 纯静态几何色块背景。零依赖、零动画、零 glow。
// 用 SVG 绘制低饱和度扁平色块（圆/圆环/圆角矩形/三角），对标参考站的"几何拼接"风格。
// 选这个方案的核心原因：它是静态矢量、无 JS 运行时、不影响包体，最稳也最轻。
// 配色：暖橙活力（橙 + 珊瑚红 + 暖粉）。

export default function GeometricBackground() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 1440 900"
      preserveAspectRatio="xMidYMid slice"
      style={{ width: '100%', height: '100%', display: 'block' }}
    >
      {/* 大圆块 - 橙 */}
      <circle cx="1160" cy="170" r="300" fill="#ff8a4c" fillOpacity="0.10" />
      {/* 大圆块 - 珊瑚红 */}
      <circle cx="200" cy="640" r="340" fill="#ff6b6b" fillOpacity="0.08" />
      {/* 中圆 - 暖粉 */}
      <circle cx="780" cy="740" r="210" fill="#ff9eb5" fillOpacity="0.07" />
      {/* 描边圆环 - 橙 */}
      <circle cx="1200" cy="600" r="150" fill="none" stroke="#ff8a4c" strokeOpacity="0.20" strokeWidth="1.5" />
      {/* 描边圆环 - 珊瑚红 */}
      <circle cx="540" cy="120" r="90" fill="none" stroke="#ff6b6b" strokeOpacity="0.16" strokeWidth="1.5" />
      {/* 圆角矩形 - 珊瑚红 平涂 */}
      <rect x="70" y="110" width="190" height="190" rx="30" fill="#ff6b6b" fillOpacity="0.06" />
      {/* 圆角矩形 - 橙 平涂 */}
      <rect x="980" y="700" width="150" height="150" rx="24" fill="#ff8a4c" fillOpacity="0.06" />
      {/* 三角形 - 暖粉 */}
      <polygon points="1000,660 1170,900 830,900" fill="#ff9eb5" fillOpacity="0.06" />
    </svg>
  )
}
