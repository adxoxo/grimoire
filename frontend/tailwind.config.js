/** @type {import('tailwindcss').Config} */
// Green-anchored dark arcane. The Grimoire's FFXV gold/violet is re-pigmented around
// the aquryu (aqua dragon) brand green from the design-en profile: leaf green is the
// primary accent, aqua the second rune, so the four node types stay distinct while the
// whole surface reads as "yours". Token NAMES are kept from the React app so markup
// ports cleanly; only the values moved.
export default {
  content: ['./index.html', './src/**/*.{svelte,ts}'],
  theme: {
    extend: {
      colors: {
        // Base layers — near-black with a green undertone (was violet)
        'bg-page': '#07100b',
        'bg-panel': '#0c1710',
        'bg-surface': '#12211a',
        surface: '#0f1a13',
        'surface-container-lowest': '#0a140e',
        'surface-container-low': '#101c15',
        'surface-container': '#14231a',
        'surface-container-high': '#1b2e22',
        'surface-container-highest': '#23392b',
        'surface-variant': '#23392b',
        'surface-bright': '#2c4735',
        'border-default': '#1e3327',
        'border-subtle': '#14201a',
        outline: '#8ca594',
        'outline-variant': '#3c5545',
        // Text
        'on-surface': '#e4efe7',
        'on-surface-variant': '#c4d3c7',
        'on-background': '#e4efe7',
        'text-muted': '#8ca594',
        'text-tertiary': '#6f8878',
        // Primary = aquryu leaf green (was gold). Bright for display, deep for fills.
        primary: '#a9e6b0',
        'primary-container': '#7fc98a',
        'on-primary': '#06210e',
        'on-primary-container': '#0c3417',
        // Secondary = warm amber, reserved for streaks/highlights only
        secondary: '#e0b85a',
        'surface-tint': '#6fbf73',
        error: '#ffb4ab',
        // The four rune colours — one glowing hue per node type
        'rune-quest': '#6fbf73', // quest line (project)  → green
        'rune-tome': '#4fb6c9', //  tome (document)       → aqua
        'rune-chronicle': '#d9a24a', // chronicle (memory) → amber
        'rune-entity': '#9d6bd9', // rune (entity)         → violet
        'status-error': '#ff6b6b',
      },
      // Architectural / angular, per the design-en profile (radius 0) softened just
      // enough to stay usable. Circular accents (bars, nodes, dots) use rounded-full.
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
        // Headers → Sora (brand display). Body → Work Sans (brand body).
        'display-lg': ['Sora', 'sans-serif'],
        'headline-lg': ['Sora', 'sans-serif'],
        'headline-md': ['Sora', 'sans-serif'],
        'headline-sm': ['Sora', 'sans-serif'],
        'headline-lg-mobile': ['Sora', 'sans-serif'],
        'body-lg': ['Work Sans', 'sans-serif'],
        'body-md': ['Work Sans', 'sans-serif'],
        'body-sm': ['Work Sans', 'sans-serif'],
        'label-md': ['Work Sans', 'sans-serif'],
      },
      fontSize: {
        'display-lg': ['44px', { lineHeight: '1.05', letterSpacing: '0.01em', fontWeight: '700' }],
        'headline-lg': ['30px', { lineHeight: '1.15', letterSpacing: '0.01em', fontWeight: '700' }],
        'headline-md': ['22px', { lineHeight: '1.25', fontWeight: '600' }],
        'headline-sm': ['16px', { lineHeight: '1.35', fontWeight: '600' }],
        'headline-lg-mobile': ['26px', { lineHeight: '1.15', fontWeight: '700' }],
        'body-lg': ['18px', { lineHeight: '1.7', fontWeight: '400' }],
        'body-md': ['15px', { lineHeight: '1.6', fontWeight: '400' }],
        'body-sm': ['13px', { lineHeight: '1.55', fontWeight: '400' }],
        'label-md': ['11px', { lineHeight: '1', letterSpacing: '0.14em', fontWeight: '500' }],
      },
    },
  },
  plugins: [],
}
