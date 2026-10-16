/** @type {import('tailwindcss').Config} */

// Ops-console palette. Colours resolve to CSS variables (src/theme-vars.css) so the
// same class names render in dark, light and print. `slate` and `indigo` are remapped
// so every page shares one neutral scale and a single desaturated accent.
const scale = (prefix, steps) =>
  Object.fromEntries(steps.map((s) => [s, `rgb(var(--${prefix}-${s}) / <alpha-value>)`]));

const graphite = scale('slate', [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 925, 950]);
const accent = scale('accent', [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]);
const status = (name) => `rgb(var(--st-${name}) / <alpha-value>)`;

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      colors: {
        slate: graphite,
        indigo: accent,
        violet: accent,
        // Semantic status colours, tuned per theme for contrast
        ok: status('ok'),
        warn: status('warn'),
        crit: status('crit'),
        info: status('info'),
        // FAA flight-category colours (standard on aviation weather charts)
        fltcat: {
          vfr: '#3fb950',
          mvfr: '#4c8eda',
          ifr: '#e5534b',
          lifr: '#c95fc9',
        },
      },
      borderRadius: {
        lg: '4px',
        xl: '5px',
        '2xl': '6px',
        '3xl': '8px',
      },
      boxShadow: {
        sm: '0 1px 1px rgba(0,0,0,0.12)',
        DEFAULT: '0 1px 2px rgba(0,0,0,0.15)',
        md: '0 1px 2px rgba(0,0,0,0.15)',
        lg: '0 2px 4px rgba(0,0,0,0.18)',
        xl: '0 2px 6px rgba(0,0,0,0.2)',
        '2xl': '0 4px 10px rgba(0,0,0,0.25)',
      },
      keyframes: {
        shimmer: { '0%': { opacity: '0.55' }, '50%': { opacity: '1' }, '100%': { opacity: '0.55' } },
      },
      animation: {
        shimmer: 'shimmer 1.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
