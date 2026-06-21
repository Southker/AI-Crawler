import Wappalyzer from 'wappalyzer';

const options = {
  debug: false,
  delay: 500,
  maxDepth: 3,
  maxUrls: 10,
  maxWait: 5000,
  recursive: true,
  userAgent: 'Mozilla/5.0 Chrome/123.0',
};

const wappalyzer = new Wappalyzer(options);

async function scan(url) {
  try {
    await wappalyzer.init();

    const site = await wappalyzer.open(url);
    const results = await site.analyze();

    console.log(JSON.stringify(results, null, 2));

  } catch (error) {
    console.error(error);
  }

  await wappalyzer.destroy();
}

// Run with:
// node crawler.js https://example.com
scan(process.argv[2]);
