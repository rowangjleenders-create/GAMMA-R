/** Unified design tokens — dark premium palette for the owner app. */
export const colors = {
  bg: '#0b0f14',
  bgElevated: '#10161f',
  card: '#151b24',
  cardAlt: '#1a2230',
  cardHover: '#1e2736',
  border: '#2a3444',
  borderSubtle: '#222a38',
  text: '#e8eef7',
  textSecondary: '#b7c3d4',
  muted: '#8b9bb0',
  accent: '#4f8cff',
  accentSoft: 'rgba(79, 140, 255, 0.14)',
  accentBorder: 'rgba(79, 140, 255, 0.35)',
  good: '#3dd68c',
  goodSoft: 'rgba(61, 214, 140, 0.14)',
  warn: '#f0b429',
  warnSoft: 'rgba(240, 180, 41, 0.14)',
  bad: '#ff5c7a',
  badSoft: 'rgba(255, 92, 122, 0.14)',
  locked: '#3a4556',
  overlay: 'rgba(0, 0, 0, 0.55)',
  white: '#ffffff',
} as const;

export const space = {
  xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 28, xxxl: 40,
} as const;

export const radius = {
  sm: 8, md: 12, lg: 16, xl: 20, pill: 999,
} as const;

export const type = {
  hero: { fontSize: 28, fontWeight: '800' as const, letterSpacing: -0.4 },
  title: { fontSize: 22, fontWeight: '800' as const, letterSpacing: -0.3 },
  section: { fontSize: 12, fontWeight: '700' as const, letterSpacing: 0.6 },
  body: { fontSize: 15, fontWeight: '400' as const },
  bodyStrong: { fontSize: 15, fontWeight: '600' as const },
  meta: { fontSize: 13, fontWeight: '400' as const },
  caption: { fontSize: 11, fontWeight: '600' as const, letterSpacing: 0.3 },
  ticker: { fontSize: 18, fontWeight: '700' as const, letterSpacing: -0.2 },
  mono: { fontSize: 13, fontWeight: '500' as const },
} as const;

export const shadow = {
  card: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.22,
    shadowRadius: 10,
    elevation: 3,
  },
} as const;
