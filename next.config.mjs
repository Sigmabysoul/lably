/** @type {import('next').NextConfig} */
const nextConfig = {
  // Move allowedDevOrigins to the top level here:
  allowedDevOrigins: [
    '192.168.1.117:3000',
    '192.168.1.117',
    'localhost:3000',
    '10.173.198.133',
    '10.41.24.133',
  ],
  async rewrites() {
    const backendUrl = (process.env.BACKEND_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
    return [
      {
        source: '/backend-api/:path*',
        destination: `${backendUrl}/:path*`,
      },
    ]
  },
};

export default nextConfig;
