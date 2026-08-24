/** @type {import('next').NextConfig} */

const nextConfig = {
  allowedDevOrigins: [
    '192.168.1.117:3000',
    '192.168.1.117',
    'localhost:3000',
    '10.173.198.133',
    '10.41.24.133:3000',
    '10.41.24.133',
  ],

  async rewrites() {
    // Local testing ke time local Python backend use karo.
    if (process.env.NODE_ENV === 'development' && !process.env.VERCEL) {
      return [
        {
          source: '/api/:path*',
          destination: 'http://127.0.0.1:8000/api/:path*',
        },
      ]
    }

    // Hosted website par Render backend use hoga.
    const backendUrl =
      process.env.BACKEND_URL || 'https://lably-48gg.onrender.com'

    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
    ]
  },
}

export default nextConfig