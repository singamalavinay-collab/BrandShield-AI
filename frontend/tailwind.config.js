/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        navy: {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          900: '#0f172a',
          950: '#0a0f1d',
        },
        brand: {
          blue: '#1d4ed8',
          'blue-light': '#3b82f6',
          'blue-subtle': '#eff6ff',
          teal: '#0d9488',
          'teal-light': '#14b8a6',
          'teal-subtle': '#f0fdfa',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      boxShadow: {
        'subtle': '0 1px 3px 0 rgba(15, 23, 42, 0.05), 0 1px 2px -1px rgba(15, 23, 42, 0.05)',
        'card': '0 1px 3px 0 rgba(15, 23, 42, 0.04), 0 4px 6px -2px rgba(15, 23, 42, 0.02)',
      },
    },
  },
  plugins: [],
};
