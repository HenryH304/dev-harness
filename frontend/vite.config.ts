import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    proxy: {
      '/api': 'http://localhost:9080',
      '/ws': {
        target: 'ws://localhost:9080',
        ws: true,
      },
    },
  },
  test: {
    environment: 'node',
  },
});
