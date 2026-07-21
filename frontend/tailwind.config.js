/** @type {import('tailwindcss').Config} */
// Dark arcane grimoire, the "Scholar" cut: near-black violet base, gold accents,
// four rune colours, Cormorant Garamond display + Spectral body. Palette restored from
// the original design (design/the_arcane_grimoire/DESIGN.md); type and chrome retyped
// per the Scholar direction (sentence-case labels, gentle tracking, softer radii).
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
      // Softly squared: still restrained, but the corners no longer read "carved".
      // Circular accents (bars, nodes, dots) use rounded-full.
      borderRadius: {
        none: '0',
        DEFAULT: '3px',
        sm: '3px',
        md: '4px',
        lg: '6px',
        xl: '8px',
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
        // Headers → Cormorant Garamond (editorial scholarly serif, the Scholar look).
        // Body → Spectral, light weights (readability wins every conflict).
        'display-lg': ['Cormorant Garamond', 'Georgia', 'serif'],
        'headline-lg': ['Cormorant Garamond', 'Georgia', 'serif'],
        'headline-md': ['Cormorant Garamond', 'Georgia', 'serif'],
        'headline-sm': ['Cormorant Garamond', 'Georgia', 'serif'],
        'headline-lg-mobile': ['Cormorant Garamond', 'Georgia', 'serif'],
        'body-lg': ['Spectral', 'serif'],
        'body-md': ['Spectral', 'serif'],
        'body-sm': ['Spectral', 'serif'],
        'label-md': ['Spectral', 'serif'],
      },
      fontSize: {
        'display-lg': ['52px', { lineHeight: '1.1', letterSpacing: '0.01em', fontWeight: '700' }],
        'headline-lg': ['35px', { lineHeight: '1.2', letterSpacing: '0.01em', fontWeight: '600' }],
        'headline-md': ['26px', { lineHeight: '1.3', fontWeight: '500' }],
        'headline-sm': ['20px', { lineHeight: '1.4', fontWeight: '600' }],
        'headline-lg-mobile': ['30px', { lineHeight: '1.2', fontWeight: '600' }],
        'body-lg': ['18px', { lineHeight: '1.6', fontWeight: '300' }],
        'body-md': ['16px', { lineHeight: '1.6', fontWeight: '400' }],
        'body-sm': ['14px', { lineHeight: '1.5', fontWeight: '400' }],
        'label-md': ['12px', { lineHeight: '1', letterSpacing: '0.03em', fontWeight: '500' }],
      },
    },
  },
  plugins: [],
}
