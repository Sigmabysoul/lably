/** @type {import('next').NextConfig} */
const nextConfig = {
  // Move allowedDevOrigins to the top level here:
  allowedDevOrigins: ['192.168.1.117:3000', '192.168.1.117', 'localhost:3000', '10.173.198.133'],
};

export default nextConfig;