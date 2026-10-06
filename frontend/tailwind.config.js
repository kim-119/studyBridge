/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  // 기존 커스텀 CSS 페이지가 깨지지 않도록 base 리셋(preflight)을 끈다.
  // → Tailwind 유틸리티 클래스는 사용한 곳에서만 적용된다.
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#ECFDF3',
          100: '#DCFCE7',
          200: '#BBF7D0',
          400: '#5FCB5B',
          500: '#22C55E',
          600: '#16A34A',
          700: '#15803D',
        },
      },
    },
  },
  plugins: [],
};
