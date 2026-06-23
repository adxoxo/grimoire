---
name: Arcane Precision
colors:
  surface: '#0e141a'
  surface-dim: '#0e141a'
  surface-bright: '#343a41'
  surface-container-lowest: '#090f15'
  surface-container-low: '#171c23'
  surface-container: '#1b2027'
  surface-container-high: '#252a32'
  surface-container-highest: '#30353d'
  on-surface: '#dee3ec'
  on-surface-variant: '#c9c4d8'
  inverse-surface: '#dee3ec'
  inverse-on-surface: '#2c3138'
  outline: '#938ea1'
  outline-variant: '#484555'
  surface-tint: '#cabeff'
  primary: '#cabeff'
  on-primary: '#31009a'
  primary-container: '#947dff'
  on-primary-container: '#2a0088'
  inverse-primary: '#603ce2'
  secondary: '#ffb95a'
  on-secondary: '#462a00'
  secondary-container: '#c68315'
  on-secondary-container: '#3d2400'
  tertiary: '#ffb780'
  on-tertiary: '#4e2600'
  tertiary-container: '#d7791f'
  on-tertiary-container: '#442000'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e6deff'
  primary-fixed-dim: '#cabeff'
  on-primary-fixed: '#1c0062'
  on-primary-fixed-variant: '#4816cb'
  secondary-fixed: '#ffddb6'
  secondary-fixed-dim: '#ffb95a'
  on-secondary-fixed: '#2a1800'
  on-secondary-fixed-variant: '#643f00'
  tertiary-fixed: '#ffdcc4'
  tertiary-fixed-dim: '#ffb780'
  on-tertiary-fixed: '#2f1400'
  on-tertiary-fixed-variant: '#6f3800'
  background: '#0e141a'
  on-background: '#dee3ec'
  surface-variant: '#30353d'
typography:
  display-xl:
    fontFamily: Libre Caslon Text
    fontSize: 48px
    fontWeight: '700'
    lineHeight: '1.1'
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Libre Caslon Text
    fontSize: 32px
    fontWeight: '600'
    lineHeight: '1.2'
  headline-lg-mobile:
    fontFamily: Libre Caslon Text
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.2'
  headline-md:
    fontFamily: Libre Caslon Text
    fontSize: 20px
    fontWeight: '500'
    lineHeight: '1.4'
  body-lg:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
  body-md:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
  label-caps:
    fontFamily: Geist
    fontSize: 11px
    fontWeight: '600'
    lineHeight: '1'
    letterSpacing: 0.1em
  mono-label:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '1'
    letterSpacing: 0.05em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base: 4px
  xs: 8px
  sm: 16px
  md: 24px
  lg: 40px
  xl: 64px
  gutter: 20px
  margin-mobile: 16px
  margin-desktop: 32px
---

## Brand & Style

This design system blends the technical rigor of modern SaaS (Linear, Vercel) with the enigmatic allure of ancient mysticism. The personality is "The Modern Alchemist"—precise, intentional, and slightly mysterious. It targets a niche of power users who value deep focus, information density, and a highly aesthetic workspace.

The visual style is a hybrid of **Minimalism** and **Tactile Dark UI**. It utilizes extreme high-density layouts, hairline strokes, and subtle luminescence to simulate the interface of a digital grimoire. Motion should be fluid and ethereal, emphasizing weightlessness through translucent layers and ambient glow rather than physical mass.

## Colors

The palette is rooted in a deep, near-black void, providing a high-contrast foundation for "magical" accents.

- **Primary (Violet):** Used for primary actions, active states, and "arcane energy" indicators. It represents discovery and potential.
- **Secondary (Ember):** Used for warnings, highlights, and critical nodes. It represents physical focus and urgent knowledge.
- **Neutral:** A range of desaturated cool grays that handle the bulk of UI structure, ensuring that color remains a meaningful signal rather than decoration.
- **Surface Strategy:** Backgrounds utilize a subtle vertical gradient from top-left to bottom-right to create a sense of atmospheric depth.

## Typography

The typographic system creates a tension between the old and the new. 

**Libre Caslon Text** is used for all major headings. It should be treated as "etched" into the UI, often appearing in high-contrast white or secondary ember.

**Geist** provides the technical backbone for body copy, data, and navigational elements. Its monospaced-adjacent aesthetic maintains the "precision tool" feel.

- **Contrast:** Maintain a sharp hierarchy. Labels should be small and uppercase to evoke index-style categorization.
- **Readability:** Body text should never fall below #a1a1aa to ensure legible contrast against the dark background.

## Layout & Spacing

The layout follows a **Fluid Grid** philosophy with high-density spacing. Inspired by developer tools, the UI maximizes screen real estate while using white space to isolate "mystical" artifacts.

- **Grid:** 12-column system on desktop, 4-column on mobile.
- **Margins:** Generous outer margins (32px+) create a sense of the interface floating in a void.
- **Rhythm:** A 4px baseline grid ensures tight, mathematical alignment. Use 1px hairline dividers (opacity 10-15%) to separate sections without adding visual bulk.
- **Mobile Reflow:** Sidebars collapse into a bottom-anchored "spell-bar" for easy thumb access.

## Elevation & Depth

Depth is conveyed through **Tonal Layers** and **Luminescence** rather than traditional drop shadows.

- **Surfaces:** Higher-level surfaces (cards, modals) are slightly lighter than the base background (#1a1b23) and feature a 1px inner border of 10% white to catch the "light."
- **Outer Glow:** Active elements use a very soft, high-spread bloom effect (e.g., `0 0 20px rgba(124, 92, 255, 0.15)`) to simulate glowing energy.
- **Glassmorphism:** Use backdrop-blur (12px+) on overlays and floating menus to maintain a sense of context within the deep space of the background.
- **Dividers:** Vertical and horizontal hairlines should be used to define the grid, appearing as faint silver or charcoal threads.

## Shapes

The shape language is primarily **Soft (0.25rem)**. This maintains a professional, sharp edge reminiscent of high-end software while avoiding the aggressive harshness of 0px corners.

- **Interaction Areas:** Buttons and inputs use the standard `rounded-sm`.
- **Large Containers:** Content cards and modals can use `rounded-lg` (0.5rem) to feel more contained and "object-like."
- **Circular Accents:** Profile icons and status indicators should remain perfect circles to contrast against the rectangular grid.

## Components

### Buttons
- **Primary:** Violet background, white text, 1px violet glow on hover.
- **Secondary/Outline:** Transparent background, 1px neutral-700 border, Ember text.
- **Ghost:** No border, Violet or Ember text, subtle background fill on hover.

### Inputs
- **Style:** Underlined or fully boxed with 1px hairline borders.
- **Focus State:** Border changes to Violet with a faint inner glow. Placeholder text is in a low-contrast neutral.

### Cards
- **Construction:** Deep gray background (#16171d), 1px stroke (#2a2b33), and a subtle `linear-gradient` border that catches the "light" at the top-left.
- **Interaction:** On hover, the border color transitions to the Primary Violet.

### Chips/Tags
- Small, uppercase Geist font. Backgrounds should be highly desaturated versions of the accent colors (e.g., 5% opacity Violet) with a solid 1px border.

### Navigation
- Sidebar-heavy with sharp serif headings for categories. Active links should be marked by a vertical violet line and a text color shift to pure white.