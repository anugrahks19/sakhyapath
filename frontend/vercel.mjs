import { deploymentEnv, routes } from '@vercel/config/v1'

// The Oracle backend stays behind its own HTTPS + Basic Auth gate.
// Vercel inserts the private Basic credential when proxying /api requests.
const suppliedOrigin = process.env.SAKHYAPATH_BACKEND_ORIGIN
if (!suppliedOrigin) {
  throw new Error('Set SAKHYAPATH_BACKEND_ORIGIN to the Oracle backend HTTPS origin in Vercel')
}

let backend
try {
  backend = new URL(suppliedOrigin)
} catch {
  throw new Error('SAKHYAPATH_BACKEND_ORIGIN must be a valid HTTPS origin')
}
if (backend.protocol !== 'https:' || backend.username || backend.password ||
    backend.pathname !== '/' || backend.search || backend.hash) {
  throw new Error('SAKHYAPATH_BACKEND_ORIGIN must be an HTTPS origin without credentials, path, query or fragment')
}
if (!process.env.SAKHYAPATH_BACKEND_BASIC_B64 ||
    !/^[A-Za-z0-9+/]+={0,2}$/.test(process.env.SAKHYAPATH_BACKEND_BASIC_B64)) {
  throw new Error('Set SAKHYAPATH_BACKEND_BASIC_B64 to the Oracle Caddy Basic credential in Vercel')
}

export const config = {
  framework: 'vite',
  outputDirectory: 'dist',
  rewrites: [
    routes.rewrite('/api/(.*)', `${backend.origin}/api/$1`, {
      requestHeaders: {
        authorization: `Basic ${deploymentEnv('SAKHYAPATH_BACKEND_BASIC_B64')}`,
      },
    }),
    routes.rewrite('/(.*)', '/index.html'),
  ],
}
