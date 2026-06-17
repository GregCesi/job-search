import type { Config } from 'tailwindcss'
import typography from '@tailwindcss/typography'

export default {
  content: [
    './app/**/*.{vue,ts}',
  ],
  plugins: [typography],
} satisfies Config
