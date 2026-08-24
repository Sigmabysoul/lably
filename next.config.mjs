/** @type {import('next').NextConfig} */
const nextConfig = {
  // Move allowedDevOrigins to the top level here:
  allowedDevOrigins: [
    '192.168.1.117:3000',
    '192.168.1.117',
    'localhost:3000',
    '10.173.198.133',
    '10.41.24.133:3000',
    '10.41.24.133',
  ],
  async rewrites() {
    // `npm run dev` does not run Vercel Python Functions. Proxy API requests
    // to the local FastAPI process only in plain Next.js development. Vercel
    // dev and production continue routing `/api/*` to `api/index.py`.
    if (process.env.NODE_ENV !== 'development' || process.env.VERCEL) return []

    return [
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:8000/api/:path*',
      },
    ]
  },
};

export default nextConfig;
