import fs from 'node:fs';
import puppeteer from 'puppeteer-core';

const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const browser = await puppeteer.launch({executablePath: process.env.CHROME_PATH,
  headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage']});
const output = {};
try {
  const page = await browser.newPage();
  await page.setRequestInterception(true);
  page.on('request', request => request.abort());
  for (const [version, expression] of Object.entries(input.expressions)) {
    output[version] = {};
    for (const [name, test] of Object.entries(input.cases)) {
      await page.setContent(test.html, {waitUntil: 'domcontentloaded'});
      output[version][name] = await page.evaluate('(' + expression + ')()');
    }
  }
} finally {
  await browser.close();
}
fs.writeFileSync(process.argv[3], JSON.stringify(output, null, 2) + '\n');
