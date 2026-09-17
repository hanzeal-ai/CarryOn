import {defineConfig} from "vite";
import react from "@vitejs/plugin-react";
import {resolve} from "node:path";
export default defineConfig({plugins:[react()],define:{"process.env.NODE_ENV":JSON.stringify("production")},build:{outDir:"../.runtime/web-build",emptyOutDir:true,cssCodeSplit:false,lib:{entry:resolve(import.meta.dirname,"src/main.jsx"),name:"CarryOnShadcnUI",formats:["iife"],fileName:()=>"shadcn-ui.js"},rollupOptions:{output:{assetFileNames:asset=>asset.name?.endsWith(".css")?"shadcn.css":"[name][extname]"}}}});
