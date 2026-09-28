import { routes } from '@vercel/config/v1'

const suppliedOrigin = process.env.SAKHYAPATH_BACKEND_ORIGIN || ''

export const config = {
  framework: 'vite',
  outputDirectory: 'dist',
  rewrites: [
    routes.rewrite('/api/(.*)', `${suppliedOrigin}/api/$1`),
    routes.rewrite('/(.*)', '/index.html'),
  ],
}
