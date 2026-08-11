import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // 同一份构建产物由 /admin/ 和 /user/ 两个前端入口复用，使用相对资源路径。
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/admin-api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/user-api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
