import { defineConfig } from 'vite';

/**
 * ⚠️ base 一定要是 '/soundproofroom/'
 *    因為這頁最後是掛在 Flask 的 /soundproofroom 路徑下,
 *    build 出來的資源連結必須帶這個前綴才找得到。
 *
 * outDir 直接輸出到 Flask 的 static 目錄,build 完不用再搬檔案。
 */
export default defineConfig({
  base: '/soundproofroom/',
  build: {
    outDir: '../static/soundproofroom',
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    port: 5173,
    open: true,
  },
});
