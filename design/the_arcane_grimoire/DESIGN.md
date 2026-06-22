---
name: The Arcane Grimoire
colors:
  surface: '#13121c'
  surface-dim: '#13121c'
  surface-bright: '#3a3842'
  surface-container-lowest: '#0e0d16'
  surface-container-low: '#1c1a24'
  surface-container: '#201e28'
  surface-container-high: '#2a2933'
  surface-container-highest: '#35333e'
  on-surface: '#e5e0ee'
  on-surface-variant: '#cdc6b7'
  inverse-surface: '#e5e0ee'
  inverse-on-surface: '#312f39'
  outline: '#969083'
  outline-variant: '#4b463b'
  surface-tint: '#d5c694'
  primary: '#ffefc0'
  on-primary: '#39300b'
  primary-container: '#e3d3a0'
  on-primary-container: '#665a32'
  inverse-primary: '#695e35'
  secondary: '#eec054'
  on-secondary: '#3f2e00'
  secondary-container: '#b38b22'
  on-secondary-container: '#372700'
  tertiary: '#ffeece'
  on-tertiary: '#3f2e00'
  tertiary-container: '#face63'
  on-tertiary-container: '#735700'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#f2e2ae'
  primary-fixed-dim: '#d5c694'
  on-primary-fixed: '#221b00'
  on-primary-fixed-variant: '#51461f'
  secondary-fixed: '#ffdf9b'
  secondary-fixed-dim: '#eec054'
  on-secondary-fixed: '#251a00'
  on-secondary-fixed-variant: '#5b4300'
  tertiary-fixed: '#ffdf99'
  tertiary-fixed-dim: '#ecc158'
  on-tertiary-fixed: '#251a00'
  on-tertiary-fixed-variant: '#5a4300'
  background: '#13121c'
  on-background: '#e5e0ee'
  surface-variant: '#35333e'
  bg-page: '#0c0b14'
  bg-panel: '#0e0d16'
  bg-surface: '#16142b'
  border-default: '#29263f'
  border-subtle: '#1d1a2e'
  text-muted: '#9b96b8'
  text-tertiary: '#6b6789'
  rune-quest: '#d4a93f'
  rune-tome: '#5b8dd9'
  rune-chronicle: '#d98b4a'
  rune-entity: '#9d6bd9'
  status-error: '#ff4d4d'
typography:
  display-lg:
    fontFamily: Cinzel
    fontSize: 48px
    fontWeight: '700'
    lineHeight: '1.1'
    letterSpacing: 0.05em
  headline-lg:
    fontFamily: Cinzel
    fontSize: 32px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: 0.02em
  headline-md:
    fontFamily: Cinzel
    fontSize: 24px
    fontWeight: '500'
    lineHeight: '1.3'
  headline-sm:
    fontFamily: Cinzel
    fontSize: 18px
    fontWeight: '600'
    lineHeight: '1.4'
  body-lg:
    fontFamily: Spectral
    fontSize: 18px
    fontWeight: '300'
    lineHeight: '1.6'
  body-md:
    fontFamily: Spectral
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
  body-sm:
    fontFamily: Spectral
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
  label-md:
    fontFamily: Spectral
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '1'
    letterSpacing: 0.1em
  headline-lg-mobile:
    fontFamily: Cinzel
    fontSize: 28px
    fontWeight: '600'
    lineHeight: '1.2'
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base: 8px
  xs: 4px
  sm: 12px
  md: 24px
  lg: 40px
  xl: 64px
  gutter: 24px
  margin: 32px
---

## Brand & Style

The design system embodies a **Dark Arcane / High-Fidelity** aesthetic, drawing inspiration from the "FFXV" style—where modern technical precision meets ancient mystical tradition. It serves as a digital sanctum for "The Grimoire," a repository of knowledge shared across autonomous agents.

The personality is **mysterious, authoritative, and sophisticated.** It should evoke the feeling of uncovering forgotten truths within a futuristic codex.

### Design Style: Dark Arcane
- **Atmosphere:** Deep, atmospheric backgrounds with high-contrast glowing elements.
- **Visual Contrast:** High-fidelity "chrome" navigation and headers contrasted against minimalist, highly legible content panels.
- **Symbolism:** Use of "Runes" (specific colors and glow effects) to categorize data types (Quest Lines, Tomes, Chronicles, Runes).
- **Tactile Detail:** Subtle gold filigree, thin borders, and glowing status indicators that suggest a physical object imbued with energy.

## Colors

The palette is rooted in a **Near-Black base with Violet undertones**, providing a canvas where Gold accents and colored Runes can "pop" with luminosity.

### Core Logic
- **Base Layers:** Use `#0c0b14` for the global background. Elevate panels with `#0e0d16` and interactive surfaces with `#16142b`.
- **Gold Accents:** Reserve `#e3d3a0` for display text and primary headings. Use deeper golds (`#d4a93f`, `#c9a13b`) for iconography and active states.
- **Rune Colors:** These define the system's "entity types." Use them for glows, edge tracing in the constellation graph, and specific UI labels.
- **Status Indicators:** Status is conveyed through **Glow Intensity**, not hue. 
    - *Reviewed:* Steady, soft glow.
    - *Unreviewed:* Faint, slow pulse.
    - *Error:* Sharp Red Rim (`#ff4d4d`).

## Typography

The typography system strikes a balance between **Thematic Display** (Cinzel) and **High Legibility** (Spectral). 

### Usage Guidelines
- **Cinzel (Headers):** Use for page titles, navigation items, and section headers. Its carved-capital feel provides the "Arcane" character. Always use **Sentence Case** for headers, except for `headline-sm` and `label-md` which may use Uppercase for structural emphasis.
- **Spectral (Body):** Used for all content panels, document text, and summaries. Use **Light weights** (300-400) to maintain a refined, bookish feel. 
- **Readability Rule:** Content panels must remain "clean and plainly readable." Do not use Cinzel for paragraphs or long-form text.

## Layout & Spacing

The Grimoire uses a **Fixed Grid** approach for content panels to ensure a scholarly, organized feel, while the Home View utilizes a **Fluid Graph** layout.

### Layout Model
- **Constellation View:** A full-bleed, fluid workspace using a force-directed layout. 
- **Content Panels:** Centered or side-docked panels with fixed max-widths (e.g., 800px for reading documents) to prevent line lengths from becoming excessive.
- **Rhythm:** An 8px base unit drives all padding and margins. Use `lg` (40px) or `xl` (64px) spacing between major sections to emphasize the "Minimalist" content philosophy.

### Breakpoints
- **Desktop:** 12-column grid, 24px gutters, 32px margins.
- **Tablet:** 8-column grid, 16px gutters, 24px margins.
- **Mobile:** 4-column grid, 12px gutters, 16px margins. Headers scale down via `headline-lg-mobile`.

## Elevation & Depth

Hierarchy is established through **Tonal Layering** and **Luminescent Glows** rather than traditional heavy shadows.

### Depth Principles
- **Surface Tiers:** Background (`#0c0b14`) is the furthest layer. Panels (`#0e0d16`) sit above. Focused or hovered elements (`#16142b`) are the "highest" physical surfaces.
- **Glow Effects:** Use `box-shadow` with high blur and low spread (e.g., `0 0 15px 0px`) using the specific Rune color to indicate importance or "active" magic.
- **Borders:** Use `#29263f` for structural borders. Apply a **Subtle Gold gradient** or a **Rune color glow** to the top edge of a panel to indicate its type (e.g., a Tome panel has a blue top border).

## Shapes

The shape language is **Sharp and Technical**, with minimal rounding to maintain a "carved" or "architectural" feel.

- **Soft (0.25rem):** Use for buttons, input fields, and standard cards. This subtle rounding prevents the UI from feeling dangerously sharp while maintaining a professional rigor.
- **Large Elements:** Containers and panels should use `rounded-lg` (0.5rem) only if they need to feel distinct from the background; otherwise, keep corners sharp.
- **Nodes:** Graph nodes are circular, representing "Runes" or "Orbs" of knowledge.

## Components

### Buttons & Controls
- **Primary:** Gold text (`#e3d3a0`) on a dark surface (`#16142b`) with a thin gold border. Hovering triggers a subtle outer glow of the primary gold.
- **Ghost/Secondary:** Muted text (`#9b96b8`) with a border that appears only on hover.

### The Constellation (Graph)
- **Nodes:** Circular icons with a central Rune symbol. The node's outer glow matches its Rune color.
- **Edges:** Thin 1px lines connecting nodes. Edges must inherit the color of the **parent** node (Quest Line/Project).

### Cards & Panels
- **Chrome:** High-fidelity detailing on the edges (gold filigree in corners or thin rune-colored top-borders).
- **Content:** The internal area must be clean. Use `Spectral` for all text inside cards. Background is always `#0e0d16`.

### Inputs & Forms
- **Style:** Underlined or subtly boxed with `#29263f`. Active focus triggers a Gold (`#d4a93f`) underline and a faint glow.
- **Typography:** Sentence case for all labels and placeholders.

### Specialized Components
- **The Review Queue:** A list of items with "Faint Pulse" glows. 
- **Skill-Tree Indicator:** Dimmed (low opacity) nodes for unvisited paths, brightening to full luminosity upon "discovery" or manual review.