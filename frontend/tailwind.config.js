/** @type {import('tailwindcss').Config} */
// Dark arcane grimoire — the FFXV-adjacent look: near-black violet base, gold accents,
// four rune colours, Cinzel display + Spectral body. Tokens restored from the original
// design (design/the_arcane_grimoire/DESIGN.md); the Svelte rewrite keeps its polish
// (canvas constellation, animations, mobile nav), only the pigment + type come home.
export default {
  content: ['./index.html', './src/**/*.{svelte,ts}'],
  theme: {
    extend: {
      colors: {
        // Base layers — near-black with a violet undertone
        'bg-page': '#0c0b14',
        'bg-panel': '#0e0d16',
        'bg-surface': '#16142b',
        surface: '#13121c',
        'surface-container-lowest': '#0e0d16',
        'surface-container-low': '#1c1a24',
        'surface-container': '#201e28',
        'surface-container-high': '#2a2933',
        'surface-container-highest': '#35333e',
        'surface-variant': '#35333e',
        'surface-bright': '#3a3842',
        'border-default': '#29263f',
        'border-subtle': '#1d1a2e',
        outline: '#969083',
        'outline-variant': '#4b463b',
        // Text
        'on-surface': '#e5e0ee',
        'on-surface-variant': '#cdc6b7',
        'on-background': '#e5e0ee',
        'text-muted': '#9b96b8',
        'text-tertiary': '#6b6789',
        // Primary = arcane gold. Pale for display text, deeper for iconography/active states.
        primary: '#ffefc0',
        'primary-container': '#e3d3a0',
        'on-primary': '#39300b',
        'on-primary-container': '#665a32',
        secondary: '#eec054',
        'surface-tint': '#d5c694',
        error: '#ffb4ab',
        // The four rune colours — one glowing hue per node type
        'rune-quest': '#d4a93f', // quest line (project)  → gold
        'rune-tome': '#5b8dd9', //  tome (document)       → arcane blue
        'rune-chronicle': '#d98b4a', // chronicle (memory) → ember
        'rune-entity': '#9d6bd9', // rune (entity)         → violet
        'status-error': '#ff4d4d',
      },
      // Sharp / technical, minimal rounding for the "carved" feel. Circular accents
      // (bars, nodes, dots) use rounded-full.
      borderRadius: {
        none: '0',
        DEFAULT: '2px',
        sm: '2px',
        md: '3px',
        lg: '3px',
        xl: '4px',
        full: '9999px',
      },
      spacing: {
        xs: '4px',
        base: '8px',
        sm: '12px',
        md: '24px',
        lg: '40px',
        xl: '64px',
        gutter: '24px',
        margin: '32px',
      },
      fontFamily: {
        // Headers → Cinzel (carved-capital serif, the FFXV-logo feel).
        // Body → Spectral, light weights (readability wins every conflict).
        'display-lg': ['Cinzel', 'serif'],
        'headline-lg': ['Cinzel', 'serif'],
        'headline-md': ['Cinzel', 'serif'],
        'headline-sm': ['Cinzel', 'serif'],
        'headline-lg-mobile': ['Cinzel', 'serif'],
        'body-lg': ['Spectral', 'serif'],
        'body-md': ['Spectral', 'serif'],
        'body-sm': ['Spectral', 'serif'],
        'label-md': ['Spectral', 'serif'],
      },
      fontSize: {
        'display-lg': ['48px', { lineHeight: '1.1', letterSpacing: '0.05em', fontWeight: '700' }],
        'headline-lg': ['32px', { lineHeight: '1.2', letterSpacing: '0.02em', fontWeight: '600' }],
        'headline-md': ['24px', { lineHeight: '1.3', fontWeight: '500' }],
        'headline-sm': ['18px', { lineHeight: '1.4', fontWeight: '600' }],
        'headline-lg-mobile': ['28px', { lineHeight: '1.2', fontWeight: '600' }],
        'body-lg': ['18px', { lineHeight: '1.6', fontWeight: '300' }],
        'body-md': ['16px', { lineHeight: '1.6', fontWeight: '400' }],
        'body-sm': ['14px', { lineHeight: '1.5', fontWeight: '400' }],
        'label-md': ['12px', { lineHeight: '1', letterSpacing: '0.1em', fontWeight: '500' }],
      },
    },
  },
  plugins: [],
}
