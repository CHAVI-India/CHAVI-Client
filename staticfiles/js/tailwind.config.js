/**
 * CHAVI Client Tailwind configuration.
 *
 * Loaded via <script src> AFTER the Tailwind PlayCDN script in base.html —
 * the CDN reads `tailwind.config` when it executes.
 *
 * Brand palette (per styleguide):
 *   Verdigris     #2a9d8f  → chavi-primary   (primary actions, success)
 *   Charcoal Blue #264653  → chavi-charcoal  (dark surfaces, info)
 *   Tuscan Sun    #e9c46a  → chavi-sun       (warning, pending)
 *   Sandy Brown   #f4a261  → chavi-sand      (accent, intermediate)
 *   Burnt Peach   #e76f51  → chavi-peach     (danger, errors)
 */
tailwind.config = {
    theme: {
        extend: {
            colors: {
                'chavi-primary': {
                    50: '#ecf9f7', 100: '#d2f0ec', 200: '#a5e1d9',
                    300: '#78d2c6', 400: '#4bb3a3', 500: '#2a9d8f',
                    600: '#228578', 700: '#1a6d62', 800: '#13554c',
                    900: '#0c3d36',
                    DEFAULT: '#2a9d8f',
                    dark: '#228578',
                },
                'chavi-primary-dark': '#228578',
                'chavi-charcoal': {
                    50: '#eef4f5', 100: '#d9e5e8', 200: '#b3cbd1',
                    300: '#8db1ba', 400: '#4d7a8a', 500: '#264653',
                    600: '#213d49', 700: '#1b333d', 800: '#152931',
                    900: '#0f1f25',
                    DEFAULT: '#264653',
                },
                'chavi-sun': {
                    50: '#fdf8ec', 100: '#faeed4', 200: '#f5dda8',
                    300: '#f0cd7d', 400: '#eabf6e', 500: '#e9c46a',
                    600: '#d9ac45', 700: '#b88d33', 800: '#8f6d28',
                    900: '#664d1d',
                    DEFAULT: '#e9c46a',
                },
                'chavi-sand': {
                    50: '#fef5ec', 100: '#fce8d3', 200: '#f9d1a7',
                    300: '#f6ba7b', 400: '#f0a565', 500: '#f4a261',
                    600: '#e58a3f', 700: '#c96f2c', 800: '#a05623',
                    900: '#77411a',
                    DEFAULT: '#f4a261',
                },
                'chavi-peach': {
                    50: '#fdf0ec', 100: '#f9ddd3', 200: '#f2baa6',
                    300: '#ec987a', 400: '#e77f62', 500: '#e76f51',
                    600: '#d95a3a', 700: '#b8482e', 800: '#913a26',
                    900: '#6b2b1c',
                    DEFAULT: '#e76f51',
                },
                // Legacy aliases kept during migration
                'chavi-secondary': '#264653',
                'chavi-accent': '#e76f51',
                'chavi-gray': '#1b333d',
                'chavi-light': '#f8f9fa',
                // Warm Paper scheme canvas — lighter than sand-50 so white cards pop
                'chavi-paper': '#fbf7f0',
                'chavi-paper-deep': '#f5eee2',
                // Cool canvas — lighter than charcoal-50 for page background
                'chavi-canvas': '#f5f8f9',
            },
            backgroundImage: {
                'chavi-gradient': 'linear-gradient(135deg, #2a9d8f 0%, #264653 100%)',
                'chavi-gradient-soft': 'linear-gradient(135deg, #d2f0ec 0%, #d9e5e8 100%)',
            },
        },
    },
};
