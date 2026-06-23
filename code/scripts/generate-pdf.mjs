import puppeteer from 'puppeteer';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Usage: node generate-pdf.mjs [input.html] [output.pdf]
// No args  -> the original current-workflow doc (unchanged behaviour).
// With args -> render any HTML; honour its CSS @page size/margins (for client docs).
const inArg = process.argv[2];
const outArg = process.argv[3];

const htmlPath = inArg ? path.resolve(inArg) : path.join(__dirname, 'current-workflow.html');
const outputPath = outArg
  ? path.resolve(outArg)
  : inArg
    ? htmlPath.replace(/\.html?$/i, '.pdf')
    : path.join(__dirname, 'KDPS - Current Workflow Understanding.pdf');

// A custom HTML (a client doc) carries its own @page CSS — let that drive the page box.
const useCssPage = Boolean(inArg);

const browser = await puppeteer.launch({ headless: true });
const page = await browser.newPage();

await page.goto(`file://${htmlPath}`, { waitUntil: 'networkidle0', timeout: 30000 });

await page.pdf({
  path: outputPath,
  format: 'A4',
  printBackground: true,
  margin: useCssPage ? undefined : { top: '0', right: '0', bottom: '0', left: '0' },
  preferCSSPageSize: useCssPage,
});

await browser.close();
console.log(`PDF generated: ${outputPath}`);
