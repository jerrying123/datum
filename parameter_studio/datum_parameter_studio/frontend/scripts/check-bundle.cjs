const esbuild = require('esbuild');
const fs = require('node:fs');

(async () => {
  const result = await esbuild.build({entryPoints:['frontend/src/app.ts'], bundle:true, format:'esm', platform:'browser', target:'es2022', minify:true, supported:{'template-literal':false}, outfile:'public/app.js', write:false});
  const expected = result.outputFiles[0].contents;
  if (!fs.existsSync('public/app.js') || !Buffer.from(expected).equals(fs.readFileSync('public/app.js'))) {
    throw new Error('public/app.js is stale; run npm run build before distribution');
  }
  console.log('Frontend bundle matches TypeScript sources.');
})().catch(error => {console.error(error.message);process.exitCode=1});
