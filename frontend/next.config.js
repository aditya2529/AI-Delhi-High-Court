/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Backend is on a separate origin in dev; CORS handled there.
  // For prod, configure a same-origin reverse-proxy in nginx (infrastructure/nginx).
  async rewrites() {
    if (process.env.NEXT_PUBLIC_API_BASE_URL) {
      return [
        {
          source: '/api/proxy/:path*',
          destination: `${process.env.NEXT_PUBLIC_API_BASE_URL}/api/v1/:path*`,
        },
      ];
    }
    return [];
  },
  // Allow inline base64 CAPTCHA images — no remote-image domain needed.
  images: {
    remotePatterns: [],
  },
};

module.exports = nextConfig;
