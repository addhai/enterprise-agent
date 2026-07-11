const fs = require('fs');

async function publish() {
  const url = process.env.CONTRACT_PUBLISH_URL;
  const token = process.env.CONTRACT_PUBLISH_TOKEN;
  const path = process.argv[2] || '../capability-contract.yaml';

  if (!url) {
    console.log('No CONTRACT_PUBLISH_URL configured; skipping remote publish.');
    process.exit(0);
  }

  const content = fs.readFileSync(path, 'utf8');
  const payload = {
    name: 'capability-contract',
    content: content
  };

  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  try {
    const res = await fetch(url, { method: 'POST', headers, body: JSON.stringify(payload) });
    if (!res.ok) {
      console.error('Publish failed with status', res.status);
      const text = await res.text();
      console.error(text);
      process.exit(2);
    }
    console.log('Contract published to registry');
  } catch (e) {
    console.error('Publish error', e.message || e);
    process.exit(2);
  }
}

publish();
