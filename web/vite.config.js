import {defineConfig} from "vite";
import {resolve} from "node:path";
export default defineConfig({build:{outDir:"../.runtime/web-build",emptyOutDir:true,cssCodeSplit:false,lib:{entry:resolve(import.meta.dirname,"src/main.js"),name:"CarryOnShadcnUI",formats:["iife"],fileName:()=>"shadcn-ui.js"},rollupOptions:{output:{assetFileNames:asset=>asset.name?.endsWith(".css")?"shadcn.css":"[name][extname]"}}}});
